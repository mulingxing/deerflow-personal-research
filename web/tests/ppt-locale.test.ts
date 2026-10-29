import { toPPTPromptLocale } from "~/core/ppt";

test.each([
  ["zh", "zh-CN"],
  ["en", "en-US"],
])("maps the %s page locale to the %s PPT prompt", (uiLocale, expected) => {
  expect(toPPTPromptLocale(uiLocale)).toBe(expected);
});
