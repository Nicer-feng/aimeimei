#!/usr/bin/env python3
"""从已确认的透明母版导出全站与移动端品牌资源；需要 Pillow。"""
from pathlib import Path
import base64
import json
import math
from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'design/brand/2026-10'
PINK = '#f4b0be'
RESAMPLE = Image.Resampling.LANCZOS


def save(image, name):
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True)


def subject(name):
    image = Image.open(SOURCE / name).convert('RGBA')
    alpha = image.getchannel('A')
    # 保留主体和边缘细毛，去掉透明抠图外围不相连的残留像素。
    region = alpha.point(lambda value: 255 if value >= 96 else 0)
    ImageDraw.floodfill(region, (image.width // 2, image.height // 2), 128)
    region = region.point(lambda value: 255 if value == 128 else 0).filter(ImageFilter.MaxFilter(9))
    image.putalpha(ImageChops.multiply(alpha, region))
    return image.crop(image.getchannel('A').getbbox())


def centered(image, size, limit, radius=None):
    scale = min(limit / image.width, limit / image.height)
    if radius:
        # 以实际不透明轮廓计算圆形安全区，避免圆形启动器切掉耳朵。
        mask = image.getchannel('A').point(lambda value: 255 if value >= 32 else 0)
        cx, cy = (image.width - 1) / 2, (image.height - 1) / 2
        maximum = 1.0
        for y in range(mask.height):
            box = mask.crop((0, y, mask.width, y + 1)).getbbox()
            if box:
                maximum = max(maximum, math.hypot(box[0] - cx, y - cy), math.hypot(box[2] - 1 - cx, y - cy))
        scale = min(scale, radius / maximum)
    width, height = round(image.width * scale), round(image.height * scale)
    result = Image.new('RGBA', (size, size))
    result.alpha_composite(image.resize((width, height), RESAMPLE), ((size - width) // 2, (size - height) // 2))
    return result


def opaque(image):
    result = Image.new('RGBA', image.size, PINK)
    result.alpha_composite(image)
    return result.convert('RGB')


def main():
    avatar = subject('avatar-source.png')
    hero = subject('hero-source.png')
    portrait = centered(avatar, 1024, 900, radius=470)
    icon = opaque(portrait)
    welcome = centered(hero, 1024, 920)
    save(portrait, 'res/meimei-avatar-cutout.png')
    save(icon, 'res/meimei-icon.png')
    save(icon.resize((512, 512), RESAMPLE), 'res/meimei-avatar.png')
    # 内嵌位图让 SVG 在 img 标签和独立查看时都能完整显示。
    avatar_data = base64.b64encode((ROOT / 'res/meimei-avatar.png').read_bytes()).decode('ascii')
    (ROOT / 'res/meimei-logo.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128" role="img" aria-label="槑槑头像">'
        '<defs><clipPath id="avatarClip"><rect width="128" height="128" rx="30"/></clipPath></defs>'
        f'<image href="data:image/png;base64,{avatar_data}" width="128" height="128" clip-path="url(#avatarClip)" preserveAspectRatio="xMidYMid meet"/></svg>\n'
    )
    save(welcome, 'res/meimei-empty-state.png')
    save(welcome, 'res/meimei-empty-state-cropped.png')
    save(welcome.resize((768, 768), RESAMPLE), 'res/meimei-login.png')
    for size in (16, 32, 64):
        save(icon.resize((size, size), RESAMPLE), f'res/favicon-{size}.png')
    save(icon.resize((180, 180), RESAMPLE), 'res/apple-touch-icon.png')
    icon.save(ROOT / 'res/favicon.ico', sizes=[(n, n) for n in (16, 32, 48, 64, 128, 256)])
    save(icon, 'mobile/ios/App/Assets.xcassets/AppIcon.appiconset/icon.png')
    save(icon.resize((512, 512), RESAMPLE), 'mobile/ios/App/Assets.xcassets/Avatar.imageset/avatar.png')
    save(welcome.resize((768, 768), RESAMPLE), 'mobile/ios/App/Assets.xcassets/Welcome.imageset/welcome.png')
    save(icon.resize((512, 512), RESAMPLE), 'mobile/android/app/src/main/res/drawable/meimei_avatar.png')
    save(welcome.resize((768, 768), RESAMPLE), 'mobile/android/app/src/main/res/drawable/meimei_welcome.png')
    foreground = centered(avatar, 1080, 640, radius=315)
    save(foreground, 'mobile/android/app/src/main/res/drawable-nodpi/ic_launcher_foreground.png')
    for density, size in [('mdpi', 48), ('hdpi', 72), ('xhdpi', 96), ('xxhdpi', 144), ('xxxhdpi', 192)]:
        save(icon.resize((size, size), RESAMPLE), f'mobile/android/app/src/main/res/mipmap-{density}/ic_launcher.png')
    print(json.dumps({'avatar_bounds': portrait.getbbox(), 'hero_bounds': welcome.getbbox(), 'adaptive_bounds': foreground.getbbox(), 'icon_alpha': icon.mode, 'background': PINK}))


if __name__ == '__main__':
    main()
