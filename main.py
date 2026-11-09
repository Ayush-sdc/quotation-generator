import math
import os
import re
import shutil
import subprocess
import uuid
from typing import List, Optional
import jinja2
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, constr

app = FastAPI(title="Quotation & Invoice Generator API")

# Configure CORS properly to prevent preflight blocking from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static assets if folder exists
if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")

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
    # Company details (all editable)
    company_name: str = "Mycelium Dynamics Pvt Ltd."
    company_address: str = "167, Kailash hills, East of Kailash, New Delhi, Delhi 110065"
    company_email: str = "connect@myceliumdynamics.com"
    company_phone: str = "+91 91834 76440"
    company_website: str = "https://www.myceliumdynamics.com/"

    # Client & quotation details
    client_name: str
    invoice_id: str
    invoice_date: str
    timeline: str = "3-4 weeks"
    projects: List[ProjectItem]

    # GST & Financial Calculations
    gst_rate: float = 18.0
    auto_roundoff: bool = True

    # Terms & Conditions (all editable)
    validity: constr(strip_whitespace=True, min_length=1, max_length=100) = "30 days"
    advance_payment: constr(strip_whitespace=True, min_length=1, max_length=100) = "50%"
    remaining_payment: constr(strip_whitespace=True, min_length=1, max_length=100) = "50%"
    scope: str = "This quotation covers only the Phase-1 MVP modules listed above."
    third_party_costs: constr(strip_whitespace=True, min_length=1, max_length=2000) = "domain, hosting, paid APIs/services, SMS/WhatsApp/email usage"
    excluded_features: constr(strip_whitespace=True, min_length=1, max_length=4000) = "customer dashboard/login, advanced multi-city builder, online payments, automated quote versioning, live hotel/flight booking APIs, AI itinerary, vendor/agent portals, mobile apps and advanced analytics"
    additional_terms: str = "Any feature not listed in the included scope will be quoted and billed separately."

    # Backwards compatibility if old clients send included_features
    included_features: Optional[str] = None

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
    if os.path.exists("index.html"):
        return FileResponse("index.html")
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
        
        # Financial and GST calculations
        subtotal = sum(p.qty * p.rate for p in data.projects)
        gst_rate = max(0.0, float(data.gst_rate)) if data.gst_rate is not None else 0.0
        gst_amount = round(subtotal * (gst_rate / 100.0), 2)
        total_before_roundoff = subtotal + gst_amount

        # Auto round off: only minuses the decimal fraction (floor), e.g. .99 -> .00, .15 -> .00
        if data.auto_roundoff:
            floor_total = math.floor(total_before_roundoff)
            roundoff_amount = round(floor_total - total_before_roundoff, 2)
            grand_total = float(floor_total)
        else:
            roundoff_amount = 0.0
            grand_total = round(total_before_roundoff, 2)

        def format_currency(val: float) -> str:
            if val == int(val):
                return f"{int(val):,}"
            return f"{val:,.2f}"

        subtotal_str = format_currency(subtotal)
        gst_amount_str = format_currency(gst_amount)
        roundoff_str = f"-{format_currency(abs(roundoff_amount))}" if roundoff_amount < 0 else "0.00"
        grand_total_str = format_currency(grand_total)
        gst_rate_str = f"{gst_rate:g}"

        safe_client_name = escape_latex(data.client_name)
        safe_invoice_id = escape_latex(data.invoice_id)
        safe_invoice_date = escape_latex(data.invoice_date)
        raw_timeline = data.timeline.strip() if data.timeline and data.timeline.strip() else "3-4 weeks"
        cleaned_timeline = re.sub(r'^timeline\s*[:\-]\s*', '', raw_timeline, flags=re.IGNORECASE)
        safe_timeline = escape_latex(cleaned_timeline)
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
            company_name=escape_latex(data.company_name),
            company_address=escape_latex(data.company_address),
            company_email=escape_latex(data.company_email),
            company_phone=escape_latex(data.company_phone),
            company_website=escape_latex(data.company_website),
            client_name=safe_client_name,
            invoice_id=safe_invoice_id,
            invoice_date=safe_invoice_date,
            timeline=safe_timeline,
            projects=safe_projects,
            gst_rate=gst_rate,
            gst_rate_display=gst_rate_str,
            subtotal=subtotal_str,
            gst_amount=gst_amount_str,
            roundoff_amount=roundoff_amount,
            roundoff=roundoff_str,
            grand_total=grand_total_str,
            validity=escape_latex(data.validity),
            advance_payment=escape_latex(data.advance_payment),
            remaining_payment=escape_latex(data.remaining_payment),
            scope=escape_latex(data.scope),
            third_party_costs=escape_latex(data.third_party_costs),
            excluded_features=escape_latex(data.excluded_features),
            additional_terms=escape_latex(data.additional_terms),
        )

        # Write the populated template to a unique temporary .tex file
        with open(tex_filename, "w", encoding="utf-8") as f:
            f.write(rendered_tex)

        # Determine LaTeX command (direct pdflatex or via WSL on Windows)
        latex_cmd = None
        if shutil.which("pdflatex"):
            latex_cmd = ["pdflatex"]
        elif shutil.which("wsl"):
            try:
                check_wsl = subprocess.run(
                    ["wsl", "which", "pdflatex"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                if check_wsl.returncode == 0 and check_wsl.stdout.strip():
                    latex_cmd = ["wsl", "pdflatex"]
            except Exception:
                pass

        if not latex_cmd:
            raise HTTPException(
                status_code=500,
                detail="pdflatex executable not found in system PATH or WSL. Ensure TeX Live is installed or run inside the Docker container."
            )

        # Execute pdflatex twice to ensure multi-pass elements (tables, totals) render correctly
        for pass_num in range(1, 3):
            try:
                process = subprocess.run(
                    latex_cmd + ["-interaction=nonstopmode", tex_filename],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            except FileNotFoundError:
                raise HTTPException(
                    status_code=500,
                    detail="pdflatex executable not found in system PATH or WSL. Ensure TeX Live is installed or run inside the Docker container."
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
