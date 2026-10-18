# ollama-chat

- 协议：[Ollama API — Chat](https://docs.ollama.com/api/chat)（原生 `/api/chat`；本端点固定 `stream:false`、`think:false`、`truncate:false`、`shift:false`）
- 结构化输出：[Structured outputs](https://docs.ollama.com/capabilities/structured-outputs)（`format` 传 JSON schema）
- 计费：本地模型不计费，货币记为 `LOCAL`
- 代码：`lib/custom_provider/endpoints.py::ENDPOINT_REGISTRY["ollama-chat"]`、`lib/text_backends/ollama.py::OllamaChatClient`、`lib/text_backends/ollama.py::OllamaChatTextBackend`
- Fixture：`tests/fixtures/ollama/`（Ollama 0.32.6 实际响应）
