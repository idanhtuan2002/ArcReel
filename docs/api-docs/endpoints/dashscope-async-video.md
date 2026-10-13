# dashscope-async-video

- 协议：[阿里云百炼视频生成](https://help.aliyun.com/zh/model-studio/use-video-generation)、[Wan 文生视频](https://help.aliyun.com/zh/model-studio/text-to-video-api-reference)、[Wan 图生视频](https://help.aliyun.com/zh/model-studio/image-to-video-general-api-reference)、[Wan 参考生视频](https://help.aliyun.com/zh/model-studio/wan-video-to-video-api-reference)、[HappyHorse 文生视频](https://help.aliyun.com/zh/model-studio/happyhorse-text-to-video-api-reference)、[图生视频](https://help.aliyun.com/zh/model-studio/happyhorse-image-to-video-api-reference)、[参考生视频](https://help.aliyun.com/zh/model-studio/happyhorse-reference-to-video-api-reference)
- 计费：[模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)
- 代码：`lib/custom_provider/endpoints.py::ENDPOINT_REGISTRY["dashscope-async-video"]`、`lib/video_backends/dashscope.py::DashScopeVideoBackend`
- R2 镜头生成依赖：[Wan 参考生视频](https://help.aliyun.com/zh/model-studio/wan-video-to-video-api-reference) 的 `parameters.prompt_extend`（默认开启改写，R2 显式下发 false）与 `reference_image` 顺序即「Image 1 / Image 2」；代码：`lib/video_backends/dashscope.py::DashScopeVideoBackend.build_submit_payload`、`r2/production_intelligence/shot_profiles.py::WAN27_TWO_VIEW_PROFILE`
