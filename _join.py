# Source - https://stackoverflow.com/a/17383621
# Posted by CnrL, modified by community. See post 'Timeline' for change history
# Retrieved 2026-06-11, License - CC BY-SA 3.0

from pathlib import Path

from PIL import Image

# Access all PNG files in directory
images = [file for file in Path("epepuy").iterdir() if file.name.endswith(".jpg")][:255]
# avg = Image.open(images[0]).resize((120, 120))
# for image in images:
#     avg = Image.blend(avg, Image.open(image).resize((120, 120)), 1 / len(images))

final = Image.new("RGBA", (1500, 1500), color="white")
for image in images:
    image = Image.open(image)
    image.putalpha(255 // len(images))
    final.paste(image, (0, 0), image)
final.convert("RGB").save("test.png")
# ImageOps.invert(
#     Image.fromarray(
#         np.average(
#             np.array([np.array(Image.open(img).resize((120, 120))) for img in images]),
#             axis=0
#         ).astype("uint8")
#     )
# ).save("test.jpg")
