"""
Remove dark background from logo.jpg and save as logo.png with transparency.
Usage: python remove_bg.py
Requires: pip install Pillow
"""
from PIL import Image

def remove_dark_background(input_path, output_path, threshold=60):
    """Remove dark/black background and save as transparent PNG."""
    img = Image.open(input_path).convert("RGBA")
    pixels = img.load()
    width, height = img.size

    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            # If the pixel is dark (close to black), make it transparent
            if r < threshold and g < threshold and b < threshold:
                pixels[x, y] = (0, 0, 0, 0)

    img.save(output_path, "PNG")
    print(f"Saved transparent logo to {output_path}")

if __name__ == "__main__":
    remove_dark_background("logo-mini.jpg", "logo-mini.png")
