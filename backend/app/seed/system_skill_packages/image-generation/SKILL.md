---
name: image-generation
description: Use when the user asks to create, generate, draw, render, or make an image, illustration, thumbnail, logo, icon, scene, product mockup, or visual concept from text.
version: 0.1.0
---

# Image Generation

Generate a new image from the user's text request through the configured image endpoint.

## Workflow

1. 将用户请求整理成简洁的图像提示词，默认使用简体中文（zh-CN），除非用户明确指定其他语言。请求不够明确或需要构图指导时，阅读 `references/image-studio-prompt.md`。
   - 对“制作周末旅行指南图”“制作福冈旅游地图”等请求，使用以下提示词结构：
     `请为 [地区] 制作旅游指南地图，采用现代编辑插画风格和极简线条人物。展示代表性地标、当地美食、游览路线和周末旅行氛围。标题和简短标签使用简体中文，不添加英文文案。`
2. Pick an aspect ratio from the user's intent:
   - `1:1` for icons, profile images, logos, and general square images.
   - `16:9` for thumbnails, banners, slides, and wide scenes.
   - `3:4` for posters, portraits, and vertical social images.
   - `9:16` for mobile wallpapers and stories.
3. Run the script from this skill directory:

```bash
python scripts/generate_image.py --prompt "IMAGE_PROMPT" --aspect-ratio "1:1" --image-size "1K"
```

Use `--aspect-ratio` with one of `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `4:1`, `1:4`.
Use `--image-size` with one of `512`, `1K`, `2K`, `4K`.
Do not pass `--model` unless the user explicitly asks for a model. The script picks the default model from the bound OpenAI-compatible endpoint:
- OpenRouter (`openrouter.ai`): `openai/gpt-5.4-image-2` via `/chat/completions` with `modalities`.
- Other OpenAI-compatible endpoints: `gpt-image-2` via `/images/generations`.

## Result

The script writes the generated image into `OUTPUTS_DIR` and prints JSON including `output_path`.
After execution, show the generated image with:

```markdown
![image](/api/conversations/<thread_id>/files/<filename>)
```

If generation fails, summarize the error and ask for a smaller or clearer prompt when helpful.
