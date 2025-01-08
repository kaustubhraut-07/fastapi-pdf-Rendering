from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import pdfplumber
import csv
import os
import io
from typing import List, Optional
from reportlab.lib.colors import white


app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_methods=["*"],
    allow_headers=["*"],
)


output_directory = "output_files"
os.makedirs(output_directory, exist_ok=True)



def resize_pdf_to_a4(input_pdf_path, output_pdf_path):
    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()
    a4_width, a4_height = A4

    for page in reader.pages:
        page_width = float(page.mediabox.width)
        page_height = float(page.mediabox.height)

        scale_x = a4_width / page_width
        scale_y = a4_height / page_height
        scale = min(scale_x, scale_y)

        page.scale(scale, scale)  
        page.mediabox.upper_right = (a4_width, a4_height)  

        writer.add_page(page)

    with open(output_pdf_path, "wb") as output_file:
        writer.write(output_file)

    return output_pdf_path


def create_subset_pdf(input_pdf, pages_to_include):
    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    for page_number in pages_to_include:
        if 1 <= page_number <= len(reader.pages):
            writer.add_page(reader.pages[page_number - 1])
    subset_pdf_path = io.BytesIO()
    writer.write(subset_pdf_path)
    subset_pdf_path.seek(0)
    return subset_pdf_path


def create_overlay_pdf(text_positions, page_width, page_height):
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    can.setFillColor(white)
    for item in text_positions:
        x, y, text = item['x'], item['y'], item['text']
        inverted_y = page_height - y

        text_width = can.stringWidth(text, 'Helvetica', 12)

        if x + text_width > A4[0]:
            x = A4[0] - text_width
        if inverted_y < 0:
            inverted_y = 0

        can.drawString(x, inverted_y -15, text)

    can.save()
    packet.seek(0)
    return packet


def add_text_to_pdf(input_pdf_stream, output_pdf_path, text_positions):
    reader = PdfReader(input_pdf_stream)
    writer = PdfWriter()

    grouped_positions = {}
    for item in text_positions:
        page_number = item['pageNumber'] - 1
        if page_number not in grouped_positions:
            grouped_positions[page_number] = []
        grouped_positions[page_number].append(item)

    page_width = A4[0]
    page_height = A4[1]

    with pdfplumber.open(input_pdf_stream) as pdf:
        for page_number in range(len(reader.pages)):
            page = reader.pages[page_number]
            if page_number in grouped_positions:
                overlay_pdf_stream = create_overlay_pdf(
                    grouped_positions[page_number], page_width, page_height
                )
                overlay_pdf = PdfReader(overlay_pdf_stream)
                overlay_page = overlay_pdf.pages[0]
                page.merge_page(overlay_page)

            writer.add_page(page)

    with open(output_pdf_path, "wb") as output_file:
        writer.write(output_file)


file_paths = []
@app.post("/process-pdf/")
async def process_pdf(
    csv_file: UploadFile,
    pdf_file: UploadFile,
    # json_positions: str = Form(...),
    json_file :UploadFile
):
    
    try:
        print(csv_file , pdf_file , json_file)
        
        csv_path = os.path.join(output_directory, csv_file.filename)
        pdf_path = os.path.join(output_directory, pdf_file.filename)
        with open(csv_path, "wb") as f:
            f.write(await csv_file.read())
        with open(pdf_path, "wb") as f:
            f.write(await pdf_file.read())

        
        import json
        text_positions = json.loads(json_file.file.read())

       
        resized_pdf_path = os.path.join(output_directory, "resized_input.pdf")
        resize_pdf_to_a4(pdf_path, resized_pdf_path)

       
        rows = []
        with open(csv_path, 'r') as file:
            csv_reader = csv.DictReader(file)
            for row in csv_reader:
                rows.append(row)

        
        output_files = []
        for idx, row in enumerate(rows):
            cleaned_row = {key.strip(): value for key, value in row.items()}
            pages = cleaned_row.get('Pages', '')
            if pages:
                pages_to_include = [int(page.strip()) for page in pages.split(',') if page.strip().isdigit()]
            else:
                with pdfplumber.open(resized_pdf_path) as pdf:
                    pages_to_include = list(range(1, len(pdf.pages) + 1))

            subset_pdf = create_subset_pdf(resized_pdf_path, pages_to_include)
            filtered_tags = [tag.copy() for tag in text_positions if tag["pageNumber"] in pages_to_include]

            for tag in filtered_tags:
                tag_text = tag["text"]
                tag["text"] = cleaned_row.get(tag_text, "")

            output_pdf_path = os.path.join(output_directory, f"output_file_{idx + 1}.pdf")
            add_text_to_pdf(subset_pdf, output_pdf_path, filtered_tags)
            output_files.append(output_pdf_path)
            print(os.getcwd())
            file_paths.append(os.path.join(os.getcwd(), "output_files", f"output_file_{idx + 1}.pdf"))
        # return JSONResponse({"message": "PDFs processed successfully", "files": output_files})
        return JSONResponse({"message": "PDFs processed successfully", "files path":file_paths })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Run the server: `uvicorn api:app --reload`
