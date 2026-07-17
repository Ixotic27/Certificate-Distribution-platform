"""
CSV Handler Module
Handles reading and searching student data from a CSV export
"""

import csv
import os
from pathlib import Path
from typing import Optional, List, Dict, Iterable


class CSVHandler:
    """Handle CSV operations for student data"""
    
    def __init__(self, csv_path: str = "students.csv"):
        """
        Initialize CSV handler
        
        Args:
            csv_path: Path to the CSV file containing student data
        """
        project_root = Path(__file__).resolve().parents[1]
        normalized = (csv_path or "").replace("\\", "/")
        candidate = Path(normalized)
        if not candidate.is_absolute():
            candidate = project_root / candidate

        self.csv_path = str(candidate)
        self._project_root = project_root

    @staticmethod
    def _normalize_key(key: str) -> str:
        # Remove all non-alphanumeric characters and convert to lowercase
        # This makes "Student Id", "Student_Id", "StudentId" all match
        return "".join(ch.lower() for ch in (key or "").strip() if ch.isalnum())

    @classmethod
    def _get_first(cls, row: Dict[str, str], keys: Iterable[str]) -> str:
        normalized_row = {cls._normalize_key(k): v for k, v in row.items()}
        for key in keys:
            value = normalized_row.get(cls._normalize_key(key))
            if value is not None:
                return str(value)
        return ""

    @staticmethod
    def _normalize_name(value: str) -> str:
        # Collapse internal whitespace and normalize case.
        return " ".join((value or "").strip().lower().split())

    @staticmethod
    def _normalize_student_id(value: str) -> str:
        # Keep IDs as strings; remove leading/trailing whitespace.
        return (value or "").strip()

    def normalize_student(self, row: Dict[str, str]) -> Dict[str, str]:
        """Return a canonical student dict regardless of CSV header variations."""
        return {
            "Name": self._get_first(row, ["Name", "Full Name", "Student Name"]),
            "Student_Id": self._get_first(row, ["Student_Id", "Student ID", "StudentId", "Student Id", "Student_Id "]),
            "Email_id": self._get_first(row, ["Email_id", "Email id", "Email", "Email ID", "Email Address"]),
            "Course": self._get_first(row, ["Course", "Program", "Branch"]),
            "Code": self._get_first(row, ["Code", "Workshop", "Event", "Batch", "Year"]),
        }
        
    def get_all_students(self) -> List[Dict[str, str]]:
        """
        Read all students from CSV file
        
        Returns:
            List of dictionaries containing student data
            
        Raises:
            FileNotFoundError: If CSV file doesn't exist
        """
        if not os.path.exists(self.csv_path):
            # Backward-compatible fallbacks (older deployments used data/students.csv)
            fallbacks = [
                str(self._project_root / "students.csv"),
                str(self._project_root / "data" / "students.csv"),
            ]
            for candidate in fallbacks:
                if os.path.exists(candidate):
                    self.csv_path = candidate
                    break
            else:
                raise FileNotFoundError(f"CSV file not found: {self.csv_path}")
        
        students: List[Dict[str, str]] = []
        # Use utf-8-sig to tolerate CSVs saved with a BOM (common with Excel/Forms exports)
        with open(self.csv_path, 'r', encoding='utf-8-sig', newline='') as file:
            reader = csv.DictReader(file)
            for row in reader:
                students.append(self.normalize_student(row))
        
        return students
    
    def find_student_by_name_and_id(self, name: str, student_id: str) -> Optional[Dict[str, str]]:
        """
        Find a student by their name and student ID
        
        Args:
            name: The student's name to search for
            student_id: The student ID to search for
            
        Returns:
            Dictionary containing student data if found, None otherwise
        """
        students = self.get_all_students()
        
        # Normalize inputs for comparison
        name_normalized = self._normalize_name(name)
        student_id_normalized = self._normalize_student_id(student_id)
        
        for student in students:
            student_name = self._normalize_name(student.get('Name', ''))
            student_sid = self._normalize_student_id(student.get('Student_Id', ''))
            
            # Match both name and student ID
            if student_name == name_normalized and student_sid == student_id_normalized:
                return student
        
        return None
    
    def generate_certificate_id(self, student_id: str) -> str:
        """
        Generate a certificate ID from student ID
        
        Args:
            student_id: The student's ID
            
        Returns:
            Certificate ID in format CERT-WORKSHOP1-{student_id}
        """
        prefix = os.getenv("CERTIFICATE_ID_PREFIX", "CERT")
        return f"{prefix}-{student_id}"
    
    def validate_csv_structure(self) -> bool:
        """
        Validate that CSV has required columns
        
        Returns:
            True if CSV structure is valid, False otherwise
        """
        required_columns = {'Name', 'Student_Id'}
        
        try:
            students = self.get_all_students()
            if not students:
                return False
            
            first_row_keys = set(students[0].keys())
            return required_columns.issubset(first_row_keys)
            
        except Exception:
            return False