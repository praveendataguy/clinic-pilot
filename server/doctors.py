SPECIALTY_DOCTORS = {
    "General Medicine": [
        ("Dr. Ayesha Rahman", 12), ("Dr. Rohan Mehta", 9), ("Dr. Fatima Al Mansoori", 15),
        ("Dr. Daniel Thomas", 7), ("Dr. Priya Nair", 11),
    ],
    "Orthopedics": [
        ("Dr. Vikram Singh", 18), ("Dr. Omar Haddad", 14), ("Dr. Karthik Subramanian", 10),
        ("Dr. Elena Petrova", 13), ("Dr. Samuel Okafor", 8),
    ],
    "Gynecology": [
        ("Dr. Meera Iyer", 16), ("Dr. Laila Hassan", 12), ("Dr. Sophia Martinez", 9),
        ("Dr. Anjali Deshpande", 14), ("Dr. Noor Al Suwaidi", 10),
    ],
    "Cardiology": [
        ("Dr. Arjun Kapoor", 20), ("Dr. Khalid Al Farsi", 17), ("Dr. Rebecca Chen", 12),
        ("Dr. Suresh Menon", 15), ("Dr. Hana Yusuf", 9),
    ],
    "Physiotherapy": [
        ("Dr. Neha Sharma", 8), ("Dr. Tariq Aziz", 11), ("Dr. Lakshmi Pillai", 10),
        ("Dr. Jacob Williams", 7), ("Dr. Mariam Qureshi", 9),
    ],
    "Pediatrics": [
        ("Dr. Divya Krishnan", 13), ("Dr. Yusuf Ibrahim", 11), ("Dr. Grace Thompson", 10),
        ("Dr. Rahul Verma", 8), ("Dr. Salma Khan", 14),
    ],
    "Dermatology": [
        ("Dr. Isha Malhotra", 9), ("Dr. Amir Sheikh", 12), ("Dr. Natalia Costa", 10),
        ("Dr. Varun Reddy", 8), ("Dr. Zainab Ali", 11),
    ],
    "ENT": [
        ("Dr. Harish Babu", 16), ("Dr. Leena Joseph", 12), ("Dr. Mustafa Karim", 9),
        ("Dr. Pooja Bhatt", 10), ("Dr. Andrew Fischer", 13),
    ],
    "Neurology": [
        ("Dr. Sanjay Rao", 19), ("Dr. Amira Nasser", 13), ("Dr. Thomas Becker", 15),
        ("Dr. Kavya Shetty", 9), ("Dr. Ibrahim Saleh", 12),
    ],
    "Dentistry": [
        ("Dr. Nadia Farouk", 10), ("Dr. Aditya Joshi", 8), ("Dr. Chloe Bennett", 7),
        ("Dr. Rashid Al Ketbi", 14), ("Dr. Swati Kulkarni", 11),
    ],
    "Ophthalmology": [
        ("Dr. Ritu Agarwal", 13), ("Dr. Hamza Syed", 10), ("Dr. Olivia Brown", 9),
        ("Dr. Manoj Pillai", 17), ("Dr. Dina Mostafa", 8),
    ],
}

DOCTORS = []
for _specialty, _people in SPECIALTY_DOCTORS.items():
    for _name, _years in _people:
        DOCTORS.append({
            "id": len(DOCTORS) + 1,
            "name": _name,
            "specialty": _specialty,
            "experience_years": _years,
        })

SPECIALTIES = list(SPECIALTY_DOCTORS)

ALIASES = {
    "ortho": "Orthopedics", "gyn": "Gynecology", "cardio": "Cardiology",
    "physio": "Physiotherapy", "general": "General Medicine", "gp": "General Medicine",
    "peds": "Pediatrics", "child": "Pediatrics", "skin": "Dermatology",
    "derma": "Dermatology", "ent": "ENT", "ear": "ENT", "neuro": "Neurology",
    "dental": "Dentistry", "dentist": "Dentistry", "eye": "Ophthalmology",
    "ophthal": "Ophthalmology",
}


def resolve_specialty(text):
    """Turn 'ortho', 'cardio', 'gyneco' etc. into a real specialty name, or None."""
    t = text.strip().lower()
    if not t:
        return None
    for alias, specialty in ALIASES.items():
        if t.startswith(alias):
            return specialty
    for s in SPECIALTIES:
        if t in s.lower() or s.lower() in t:
            return s
    return None


def find_doctor(text):
    """Find doctors by list number (e.g. '7') or by name (full or partial, ignores 'Dr.')."""
    t = str(text).strip().rstrip(".)")
    if t.isdigit():
        return [d for d in DOCTORS if d["id"] == int(t)]
    t = t.lower().replace("dr.", "").replace("dr ", "").strip()
    if not t:
        return []
    exact = [d for d in DOCTORS if d["name"].lower().replace("dr. ", "") == t]
    if len(exact) == 1:
        return exact
    return [d for d in DOCTORS if t in d["name"].lower()]