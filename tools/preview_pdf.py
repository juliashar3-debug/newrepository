"""Render PDF pages for visual review, preserving the original document."""
import argparse
from pathlib import Path


def render_pdf(source, output, scale=1.3):
    import pypdfium2 as pdfium
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose an empty preview directory to preserve existing files.')
    output.mkdir(parents=True, exist_ok=True)
    with pdfium.PdfDocument(str(source)) as document:
        for index in range(len(document)):
            page = document[index]
            try:
                bitmap = page.render(scale=scale)
                try:
                    bitmap.to_pil().save(output / f'slide-{index + 1:02}.png')
                finally:
                    bitmap.close()
            finally:
                page.close()
        return len(document)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print('Rendered pages:', render_pdf(args.pdf, args.output))
