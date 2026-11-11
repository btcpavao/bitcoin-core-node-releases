#!/usr/bin/python3
"""Render Node boot text with Vault's text_asset helper and font sizes.
Source: bitcoin-core-vault integration 9e9486742191d27b8571292034187c3079a9fd60.
Common logos, progress track/fill and Plymouth script are copied unchanged.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def text_asset(text, font, colour):
    dummy = Image.new(
        "RGBA",
        (1, 1),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(dummy)
    box = draw.textbbox((0, 0), text, font=font)

    image = Image.new(
        "RGBA",
        (
            box[2] - box[0] + 6,
            box[3] - box[1] + 6,
        ),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(image)

    draw.text(
        (
            3 - box[0],
            3 - box[1],
        ),
        text,
        font=font,
        fill=colour,
    )

    return image

def main():
    output=Path(__file__).resolve().parents[1]/'runtime/usr/share/plymouth/themes/core-node'
    output.mkdir(parents=True,exist_ok=True)
    regular='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    bold='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
    for name,text,font,size in [
        ('boot-title.png','Bitcoin Core Node',bold,24),
        ('boot-line1.png','Bitcoin Core online node environment.',regular,19),
        ('boot-line2.png','Starting your Bitcoin Core workspace',regular,19),
    ]:
        text_asset(text,ImageFont.truetype(font,size),(255,255,255,255)).save(output/name)
    text_asset('Powered by Debian GNU/Linux',ImageFont.truetype(regular,16),
               (176,176,176,255)).save(output/'powered-by-debian.png')

if __name__=='__main__':
    main()

