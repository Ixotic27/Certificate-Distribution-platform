"""
FastAPI Certificate Distribution System
Main application with all API endpoints
"""

import os
from pathlib import Path
from typing import Dict, Any, List

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    # dotenv is optional on Render; env vars are injected there.
    pass

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.csv_handler import CSVHandler
from app.certificate_generator import CertificateGenerator


# Initialize FastAPI app
app = FastAPI(
    title="Certificate Distribution System",
    description="A system for generating and distributing certificates",
    version="1.0.0"
)

# ---- Environment / Paths (Render-friendly) ----

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "templates"

CSV_PATH = os.getenv("CSV_PATH", "students.csv")
MANAGEMENT_CSV_PATH = os.getenv("MANAGEMENT_CSV_PATH", "management.csv")
CERTIFICATES_DIR = os.getenv("CERTIFICATES_DIR", "certificates")
TEMPLATE_IMAGE = os.getenv("CERTIFICATE_TEMPLATE_IMAGE", "templates/student_certificate_template.jpg")
MANAGEMENT_TEMPLATE_IMAGE = os.getenv("MANAGEMENT_CERTIFICATE_TEMPLATE_IMAGE", "templates/management_certificate_template.jpeg")

# Admin key for protected endpoints (optional)
ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def _as_abs(path_str: str) -> str:
    # Allow Windows-style env var paths (e.g., "data\\students.csv") even on Linux.
    normalized = (path_str or "").replace("\\", "/")
    p = Path(normalized)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return str(p)


# Add CORS middleware (configure allowed origins via env var)
origins_raw = os.getenv("CORS_ALLOW_ORIGINS", "*")
allow_origins: List[str] = [o.strip() for o in origins_raw.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins if allow_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
)


# Initialize handlers for both students and management
csv_handler = CSVHandler(_as_abs(CSV_PATH))
management_csv_handler = CSVHandler(_as_abs(MANAGEMENT_CSV_PATH))

# Initialize separate certificate generators for students and management
student_cert_generator = CertificateGenerator(
    template_path=_as_abs(TEMPLATE_IMAGE),
    output_dir=_as_abs(CERTIFICATES_DIR),
)

management_cert_generator = CertificateGenerator(
    template_path=_as_abs(MANAGEMENT_TEMPLATE_IMAGE),
    output_dir=_as_abs(CERTIFICATES_DIR),
)


# Serve templates directory as static (optional assets)
# Serve templates directory as static files at /templates URL
if TEMPLATES_DIR.exists():
    app.mount("/templates", StaticFiles(directory=str(TEMPLATES_DIR)), name="templates")



@app.get("/", response_class=HTMLResponse)
async def home():
    """
    Serve the main HTML interface
    
    Returns:
        HTML page with certificate search form
    """
    html_path = TEMPLATES_DIR / "index.html"

    if not html_path.exists():
        raise HTTPException(status_code=500, detail="Template file not found")

    with open(html_path, 'r', encoding='utf-8') as file:
        html_content = file.read()

    return HTMLResponse(content=html_content)


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for monitoring
    
    Returns:
        Status message
    """
    csv_abs = _as_abs(CSV_PATH)
    management_csv_abs = _as_abs(MANAGEMENT_CSV_PATH)
    template_abs = _as_abs(TEMPLATE_IMAGE)
    management_template_abs = _as_abs(MANAGEMENT_TEMPLATE_IMAGE)
    certificates_abs = _as_abs(CERTIFICATES_DIR)

    return {
        "status": "running",
        "paths": {
            "csv": csv_abs,
            "csv_exists": Path(csv_abs).exists(),
            "management_csv": management_csv_abs,
            "management_csv_exists": Path(management_csv_abs).exists(),
            "template_image": template_abs,
            "template_exists": Path(template_abs).exists(),
            "management_template_image": management_template_abs,
            "management_template_exists": Path(management_template_abs).exists(),
            "certificates_dir": certificates_abs,
            "certificates_dir_exists": Path(certificates_abs).exists(),
        },
    }


@app.get("/verify")
async def verify_certificate(
    name: str, 
    student_id: str,
    user_type: str = Query("student", regex="^(student|management)$")
) -> Dict[str, Any]:
    """
    Verify a certificate and return student/management information
    
    Args:
        name: The person's name
        student_id: The person's ID
        user_type: Type of user - 'student' or 'management'
        
    Returns:
        Person information and validity status
        
    Raises:
        HTTPException: If person not found
    """
    # Select the appropriate handler based on user type
    handler = csv_handler if user_type == "student" else management_csv_handler
    
    try:
        person = handler.find_student_by_name_and_id(name, student_id)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=503,
            detail=f"{user_type.capitalize()} database CSV not available: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error while verifying {user_type}: {str(e)}",
        )
    
    if not person:
        raise HTTPException(
            status_code=404, 
            detail=f"{user_type.capitalize()} not found with name: {name} and ID: {student_id}"
        )
    
    certificate_id = handler.generate_certificate_id(person.get("Student_Id"))
    
    return {
        "name": person.get("Name"),
        "email": person.get("Email_id"),
        "student_id": person.get("Student_Id"),
        "course": person.get("Course"),
        "certificate_id": certificate_id,
        "user_type": user_type,
        "valid": True
    }



@app.get("/certificate")
async def get_certificate(
    name: str,
    student_id: str,
    user_type: str = Query("student", regex="^(student|management)$"),
    force: bool = Query(False, description="Regenerate the certificate PDF even if it already exists"),
):
    """
    Generate certificate if not exists and return as downloadable PDF
    
    Args:
        name: The person's name
        student_id: The person's ID
        user_type: Type of user - 'student' or 'management'
        force: Whether to regenerate the certificate
        
    Returns:
        PDF file as download
        
    Raises:
        HTTPException: If person not found in database
    """
    # Select the appropriate handler based on user type
    handler = csv_handler if user_type == "student" else management_csv_handler
    cert_gen = student_cert_generator if user_type == "student" else management_cert_generator
    
    # Verify person exists
    try:
        person = handler.find_student_by_name_and_id(name, student_id)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=503,
            detail=f"{user_type.capitalize()} database CSV not available: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error while looking up {user_type}: {str(e)}",
        )
    
    if not person:
        raise HTTPException(
            status_code=404,
            detail=f"{user_type.capitalize()} not found with name: {name} and ID: {student_id}"
        )
    
    # Generate certificate ID
    certificate_id = handler.generate_certificate_id(person.get("Student_Id"))
    
    # Render/WebService: cache PDFs on disk
    if force or (not cert_gen.certificate_exists(certificate_id)):
        try:
            cert_gen.generate_certificate(
                student_name=person.get("Name"),
                certificate_id=certificate_id,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error generating certificate: {str(e)}")

    cert_path = cert_gen.get_certificate_path(certificate_id)
    return FileResponse(path=cert_path, media_type="application/pdf", filename=f"{certificate_id}.pdf")


@app.get("/generate-all")
async def generate_all_certificates(
    admin_key: str = Query(..., description="Admin key for authorization"),
    user_type: str = Query("student", regex="^(student|management)$")
) -> Dict[str, Any]:
    """
    Admin endpoint to generate all certificates from CSV
    Protected by admin key
    
    Args:
        admin_key: Admin authorization key
        user_type: Type of users to generate certificates for - 'student' or 'management'
        
    Returns:
        Summary of generated certificates
        
    Raises:
        HTTPException: If admin key is invalid or generation fails
    """
    # Verify admin key (only enforced if ADMIN_KEY is set)
    if ADMIN_KEY and admin_key != ADMIN_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid admin key"
        )
    
    # Select the appropriate handler based on user type
    handler = csv_handler if user_type == "student" else management_csv_handler
    cert_gen = student_cert_generator if user_type == "student" else management_cert_generator
    
    try:
        people = handler.get_all_students()
        generated = []
        skipped = []
        
        for person in people:
            person_id = person.get("Student_Id")
            name = person.get("Name")
            
            # Generate certificate ID
            certificate_id = handler.generate_certificate_id(person_id)
            
            # Skip if already exists
            if cert_gen.certificate_exists(certificate_id):
                skipped.append(certificate_id)
                continue
            
            # Generate certificate
            cert_gen.generate_certificate(
                student_name=name,
                certificate_id=certificate_id
            )
            generated.append(certificate_id)
        
        return {
            "success": True,
            "user_type": user_type,
            "total_people": len(people),
            "generated": len(generated),
            "skipped": len(skipped),
            "generated_ids": generated,
            "skipped_ids": skipped
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error generating certificates: {str(e)}"
        )


# Run with: uvicorn app.main:app --reload
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)