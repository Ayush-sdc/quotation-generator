# Mycelium Dynamics - Automated Quotation Generation System

A production-ready, full-stack microservice designed to generate highly precise, publication-grade PDF quotations. This system utilizes a lightweight HTML/JS frontend to capture dynamic itemized breakdowns, which are posted to a containerized FastAPI backend. The backend dynamically merges the JSON payload into an advanced LaTeX template using Jinja2 and compiles the document into a branded PDF with automated math totals.

## 🚀 Tech Stack & Architecture
* **Frontend:** HTML5, CSS3, JavaScript (Vanilla fetch API)
* **Backend:** Python 3.9, FastAPI, Uvicorn, Pydantic, Jinja2
* **Typesetting Engine:** TeX Live (`pdflatex`, `xfp`, `tikz`)
* **Containerization:** Docker (Debian Slim Linux environment)

## 📦 Prerequisites
Before running this project, ensure you have the following installed on your system:
* [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Running)
* [Python 3.x](https://www.python.org/downloads/) (For the local frontend server)
* Git (For version control)

---

## 🛠️ Step-by-Step Installation & Usage

### Step 1: Start the Backend (Docker)
The backend is completely containerized to ensure the massive TeX Live LaTeX environment runs isolated from your local machine.

1. Open a terminal in the root directory of the project.
2. Build the Docker image (this may take a few minutes the first time to download LaTeX dependencies):
   ```bash
   docker build -t quotation-generator .