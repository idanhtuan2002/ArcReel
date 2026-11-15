# ark-seedream

- 协议：[BytePlus ModelArk Image generation API](https://docs.byteplus.com/en/docs/ModelArk/1541523)（火山方舟同一协议：`POST /api/v3/images/generations`，参考图 `image` 字段，`watermark` 默认 true）
- 计费：[BytePlus ModelArk 定价](https://docs.byteplus.com/en/docs/ModelArk/1544106)
- 代码：`lib/custom_provider/endpoints.py::ENDPOINT_REGISTRY["ark-seedream"]`、`lib/image_backends/ark.py::ArkImageBackend`
