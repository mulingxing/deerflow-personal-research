// 中文注释：在 Marp 把幻灯片压成图片之前，检查实际排版是否超出画布。
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const { pathToFileURL } = require("node:url");

async function main() {
  const cliPath = fs.realpathSync(process.argv[2]);
  const htmlPath = path.resolve(process.argv[3]);
  const browserPath =
    process.argv[4] || process.env.MARP_BROWSER_PATH || process.env.PUPPETEER_EXECUTABLE_PATH;
  const puppeteer = createRequire(cliPath)("puppeteer-core");
  const launchOptions = browserPath
    ? { executablePath: browserPath, headless: true }
    : { channel: "chrome", headless: true };
  const browser = await puppeteer.launch(launchOptions);

  try {
    const page = await browser.newPage();
    await page.setJavaScriptEnabled(false);
    await page.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1 });
    await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "load" });
    await page.evaluate(async () => {
      await document.fonts.ready;
    });

    const overflowSlides = await page.evaluate(() => {
      const sections = [
        ...document.querySelectorAll("svg[data-marpit-svg] foreignObject > section"),
      ];
      if (sections.length === 0) {
        throw new Error("Marp HTML contains no slides");
      }

      return sections.flatMap((section, index) => {
        const slide = section.getBoundingClientRect();
        const style = getComputedStyle(section);
        const scaleX = slide.width / section.clientWidth;
        const scaleY = slide.height / section.clientHeight;
        const content = [...section.children].filter(
          (element) =>
            element.getClientRects().length > 0 &&
            !element.hasAttribute("data-marpit-advanced-background"),
        );
        const bounds = content.map((element) => element.getBoundingClientRect());
        const left = Math.min(
          ...bounds.map((box) => (box.left - slide.left) / scaleX),
          section.clientWidth,
        );
        const top = Math.min(
          ...bounds.map((box) => (box.top - slide.top) / scaleY),
          section.clientHeight,
        );
        const right = Math.max(
          ...bounds.map((box) => (box.right - slide.left) / scaleX),
          0,
        );
        const bottom = Math.max(
          ...bounds.map((box) => (box.bottom - slide.top) / scaleY),
          0,
        );
        const innerOverflow = [...section.querySelectorAll("pre, table, td, th")].some(
          (element) =>
            element.scrollWidth > element.clientWidth + 2 ||
            element.scrollHeight > element.clientHeight + 2,
        );
        const outside =
          section.scrollWidth > section.clientWidth + 2 ||
          section.scrollHeight > section.clientHeight + 2 ||
          left < parseFloat(style.paddingLeft) - 2 ||
          top < parseFloat(style.paddingTop) - 2 ||
          right > section.clientWidth - parseFloat(style.paddingRight) + 2 ||
          bottom > section.clientHeight - parseFloat(style.paddingBottom) + 2 ||
          innerOverflow;
        return outside ? [index + 1] : [];
      });
    });
    process.stdout.write(JSON.stringify({ overflow_slides: overflowSlides }));
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  process.stderr.write(String(error));
  process.exitCode = 1;
});
