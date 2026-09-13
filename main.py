import os
import re
import subprocess
import uuid
from typing import List
import jinja2
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Quotation & Invoice Generator API")

# Configure CORS properly to prevent preflight blocking from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# LaTeX special character escaping mapping
LATEX_CONVERSIONS = {
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "\\": r"\textbackslash{}",
}
LATEX_REGEX = re.compile(r'[&%$#_{}~^\\]')

def escape_latex(text: str) -> str:
    """Escapes LaTeX special characters in user input to prevent syntax errors and injection."""
    if not isinstance(text, str):
        return str(text)
    return LATEX_REGEX.sub(lambda match: LATEX_CONVERSIONS[match.group(0)], text)

# Configure Jinja2 to search 'templates' folder and current directory
template_loader = jinja2.FileSystemLoader(["templates", "."])
env = jinja2.Environment(
    loader=template_loader,
    block_start_string="<%",
    block_end_string="%>",
    variable_start_string="<<",
    variable_end_string=">>",
    comment_start_string="<#",
    comment_end_string="#>",
)
env.filters["latex_escape"] = escape_latex

class ProjectItem(BaseModel):
    category: str
    description: str
    qty: int
    rate: float

class InvoiceRequest(BaseModel):
    client_name: str
    invoice_id: str
    invoice_date: str
    projects: List[ProjectItem]

def cleanup_temp_files(file_paths: List[str]):
    """Safely removes temporary compilation files after response delivery."""
    for path in file_paths:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

@app.get("/healthz")
async def healthz():
    return {"status": "healthy"}



@app.get("/")
async def root():
    return {
        "message": "Mycelium Dynamics API is Live!", 
        "instruction": "This is the backend engine. Please use the Vercel URL to access the Quotation Generator UI."
    }


@app.post("/generate-pdf")
async def generate_pdf(data: InvoiceRequest, background_tasks: BackgroundTasks):
    unique_id = str(uuid.uuid4())
    tex_filename = f"temp_{unique_id}.tex"
    pdf_filename = f"temp_{unique_id}.pdf"
    aux_filename = f"temp_{unique_id}.aux"
    log_filename = f"temp_{unique_id}.log"
    out_filename = f"temp_{unique_id}.out"
    files_to_clean = [tex_filename, pdf_filename, aux_filename, log_filename, out_filename]

    try:
        # Load and render the LaTeX template with sanitized user data
        template = env.get_template("invoice.tex")
        
        safe_client_name = escape_latex(data.client_name)
        safe_invoice_id = escape_latex(data.invoice_id)
        safe_invoice_date = escape_latex(data.invoice_date)
        safe_projects = [
            {
                "category": escape_latex(p.category),
                "description": escape_latex(p.description),
                "qty": p.qty,
                "rate": p.rate,
            }
            for p in data.projects
        ]

        rendered_tex = template.render(
            client_name=safe_client_name,
            invoice_id=safe_invoice_id,
            invoice_date=safe_invoice_date,
            projects=safe_projects
        )

        # Write the populated template to a unique temporary .tex file
        with open(tex_filename, "w", encoding="utf-8") as f:
            f.write(rendered_tex)

        # Execute pdflatex twice to ensure multi-pass elements (tables, totals) render correctly
        for pass_num in range(1, 3):
            try:
                process = subprocess.run(
                    ["pdflatex", "-interaction=nonstopmode", tex_filename],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            except FileNotFoundError:
                raise HTTPException(
                    status_code=500,
                    detail="pdflatex executable not found in system PATH. Ensure TeX Live is installed or run inside the Docker container."
                )

            if process.returncode != 0:
                stdout_output = process.stdout.decode("utf-8", errors="ignore")
                print(f"LaTeX Compilation Error Output (Pass {pass_num}):\n", stdout_output)
                
                # Extract primary LaTeX error messages starting with '!'
                latex_errors = [line.strip() for line in stdout_output.splitlines() if line.startswith("!")]
                err_summary = " | ".join(latex_errors[:3]) if latex_errors else "LaTeX compilation crashed."
                raise HTTPException(
                    status_code=500, 
                    detail=f"Compilation failed: {err_summary}"
                )

        if not os.path.exists(pdf_filename):
            raise HTTPException(status_code=500, detail="PDF compilation completed, but the output file was not found.")

        # Register background task to clean up temporary files after streaming
        background_tasks.add_task(cleanup_temp_files, files_to_clean)

        return FileResponse(
            pdf_filename,
            media_type="application/pdf",
            filename=f"Quotation_{data.invoice_id}.pdf"
        )

    except HTTPException as he:
        cleanup_temp_files(files_to_clean)
        raise he
    except Exception as e:
        cleanup_temp_files(files_to_clean)
        raise HTTPException(status_code=500, detail=str(e))