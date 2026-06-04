import fitz
import os
import tempfile
from pathlib import Path

# Mock values from the user's logs
pdf_id = 36
jbmono_file = r"D:\docs\PROJECTS\QMS\prometrix\backend\app\fonts\JetBrainsMono-Bold.ttf"

# 1. Mock path resolution
# Normally get_pdf_path_from_document would find the file.
# I'll try to find any PDF in the blob_data to test with.
blob_dir = Path("blob_data")
pdf_files = list(blob_dir.glob("*.pdf")) + list(blob_dir.glob("*.jpg"))

if not pdf_files:
    print("No files found in blob_data to test with.")
    exit(1)

test_file = pdf_files[0]
print(f"Testing with file: {test_file}")

try:
    doc = fitz.open(str(test_file))
    print(f"Opened document. Pages: {len(doc)}")
    
    page = doc[0]
    
    # Test font registration
    if os.path.exists(jbmono_file):
        print(f"Registering font: {jbmono_file}")
        page.insert_font(fontname="jbmono", fontfile=jbmono_file)
        print("Font registered.")
    
    # Test shape drawing
    sh = page.new_shape()
    sh.draw_circle(fitz.Point(100, 100), 10)
    sh.finish(color=(1,0,0), fill=(1,0,0))
    sh.commit()
    print("Circle drawn.")
    
    # Test text insertion
    page.insert_text(fitz.Point(110, 110), "Test", fontname="jbmono", fontsize=10)
    print("Text inserted.")
    
    # Test save
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf", prefix="test_")
    os.close(fd)
    doc.save(tmp_path)
    doc.close()
    print(f"Saved to {tmp_path}")
    os.remove(tmp_path)

except Exception as e:
    import traceback
    print("DIAGNOSTIC FAILED:")
    print(traceback.format_exc())
