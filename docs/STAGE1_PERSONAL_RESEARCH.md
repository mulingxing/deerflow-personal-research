# 第一阶段：个人资料研究

## 现在能做什么

在“设置 → Resources（资源）”上传 Markdown、TXT、PDF 或 Word（`.docx`）文件，等待解析和向量索引完成。默认单文件上限为 50 MB，可通过 `RAG_MAX_UPLOAD_MB` 调整。上传请求按块接收，后台任务处理文件，页面会显示进度和失败原因；刷新页面后仍可查看当前任务状态。索引写入项目下的 `.runtime/qdrant`，重启后可以继续使用已经导入的资料。

聊天框可以选择“仅联网”“仅我的资料”“资料 + 联网”，并勾选一份或多份资料。仅我的资料模式会关闭联网搜索工具；资料 + 联网模式会同时提供所选资料的检索工具和网页搜索工具。资料检索会先限定所选文件，再按语义相似度查找片段。PDF 片段保留页码，Word 和 Markdown 片段保留章节标题，回答中的来源列表可显示这些位置。

## 首次启用

在项目根目录的 `.env` 中加入以下配置，然后重启后端：

```dotenv
RAG_PROVIDER=qdrant
QDRANT_LOCATION=.runtime/qdrant
QDRANT_COLLECTION=documents
QDRANT_EMBEDDING_PROVIDER=fastembed
QDRANT_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
QDRANT_AUTO_LOAD_EXAMPLES=false
RAG_MAX_UPLOAD_MB=50
RAG_MAX_CHUNKS=5000
```

`Qdrant` 是保存资料片段向量的数据库；此处使用项目本地目录，无须单独启动数据库服务。`FastEmbed` 是在本机 CPU 上运行的向量模型，用来把文本变成便于语义检索的数字向量。它第一次使用时需要联网下载模型，之后使用本地缓存。项目现有的大模型配置仍用于生成回答。

操作顺序：启动前后端 → 打开“设置 → Resources（资源）” → 上传并等待完成 → 回到聊天框选择模式和资料 → 提问，例如“按照我上传的论文解释第二章的方法，并标出来源页码”。

## 使用边界

- “仅我的资料”表示不调用**网页搜索工具**，不表示整个系统完全离线。当前项目的大模型若配置为云服务，检索出的资料片段仍会发送给该模型生成回答。企业保密资料接入前，应先核对模型服务和数据使用要求。
- 当前 PDF 只提取文字层；扫描件需要先做 OCR（光学文字识别）。加密 PDF 和旧版 `.doc` 暂不支持。
- 检索会找到与问题最相关的片段，不能保证一次覆盖整本书或整篇长论文。要系统学习长材料，适合按章节分次提问。
- `RAG_MAX_UPLOAD_MB` 是单文件大小上限；`RAG_MAX_CHUNKS` 默认最多 5000 个文本块，是索引耗时和内存的保护限制。文件虽然在大小上限内，内容过长仍可能明确报错。
- 本地目录模式的 Qdrant 只适合一个后端进程使用；若部署多个后端进程，应改用独立的 Qdrant 服务。
- 关闭网页搜索后，大模型仍可能依据自身训练知识补充内容；回答中的来源应以资料片段为准。更严格的逐条证据校验属于后续阶段。

## 实现位置

前端上传与任务状态：`web/src/app/settings/tabs/rag-tab.tsx`；模式和资料选择：`web/src/app/chat/components/input-box.tsx`；上传 API：`src/server/app.py`；文件解析：`src/rag/ingestion.py`；任务状态：`src/rag/upload_jobs.py`；本地索引与检索：`src/rag/qdrant.py`。
