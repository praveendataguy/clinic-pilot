"""Country-aware phone validation for the receptionist."""
import re

import phonenumbers
from phonenumbers import PhoneNumberType as T

ASK_AGAIN = "Please enter a valid phone number."

ALIASES = {
    "india": "IN", "uae": "AE", "united arab emirates": "AE", "dubai": "AE",
    "uk": "GB", "united kingdom": "GB", "england": "GB", "britain": "GB",
    "us": "US", "usa": "US", "united states": "US", "america": "US",
    "saudi arabia": "SA", "ksa": "SA", "qatar": "QA", "kuwait": "KW", "oman": "OM",
    "bahrain": "BH", "pakistan": "PK", "bangladesh": "BD", "sri lanka": "LK",
    "nepal": "NP", "singapore": "SG", "malaysia": "MY", "australia": "AU",
    "canada": "CA", "germany": "DE", "france": "FR", "philippines": "PH",
    "egypt": "EG", "south africa": "ZA", "new zealand": "NZ", "ireland": "IE",
}


def resolve_region(country):
    """'India', 'IN', '+91', '91' -> 'IN'. Returns None if unknown."""
    t = str(country).strip().lower()
    if not t:
        return None
    if t in ALIASES:
        return ALIASES[t]
    digits = t.lstrip("+")
    if digits.isdigit():
        regions = phonenumbers.region_codes_for_country_code(int(digits))
        return regions[0] if regions else None
    if len(t) == 2 and t.upper() in phonenumbers.SUPPORTED_REGIONS:
        return t.upper()
    return None


def _longest_run(s, step):
    """Longest run where each digit moves by `step` (+1 up, -1 down, 0 same)."""
    best = run = 1
    for a, b in zip(s, s[1:]):
        if int(b) - int(a) == step:
            run += 1
            best = max(best, run)
        else:
            run = 1
    return best


def fake_reason(national):
    """Return a short reason if the digits look made-up, else None."""
    d = national
    if len(d) < 6:
        return "too short"
    if len(set(d)) == 1:
        return "the same digit repeated"
    if _longest_run(d, 0) >= 5:
        return "one digit repeated many times"
    if d.count("0") >= 5 and d.count("0") / len(d) > 0.4:
        return "too many zeros"
    if "00000" in d:
        return "too many zeros"
    if _longest_run(d, 1) >= 5:
        return "continuous digits like 12345"
    if _longest_run(d, -1) >= 5:
        return "reversed digits like 54321"
    for size in range(1, len(d) // 2 + 1):
        if len(d) % size == 0 and d[:size] * (len(d) // size) == d:
            return "a repeating pattern"
    if re.search(r"(\d\d)\1{2,}", d):
        return "a repeating pattern"
    if len(set(d)) <= 2 and len(d) >= 8:
        return "too few different digits"
    return None


TYPE_NAMES = {
    T.MOBILE: "mobile",
    T.FIXED_LINE: "landline",
    T.FIXED_LINE_OR_MOBILE: "mobile or landline",
    T.TOLL_FREE: "toll-free",
    T.PREMIUM_RATE: "premium-rate",
    T.VOIP: "voip",
}


def validate_phone(country, phone, kind="any"):
    """Check a phone number for the patient's country.

    kind: "any", "mobile" or "landline".
    Success: {"ok": True, "e164": "+919841276053", "country": "IN", "country_code": 91,
              "national": "9841276053", "type": "mobile"}
    Failure: {"ok": False, "error": "..."}  (the error is safe to read to the caller)
    """
    region = resolve_region(country)
    if region is None:
        return {"ok": False, "error": "I don't recognise that country. Which country is the patient in?"}
    cc = phonenumbers.country_code_for_region(region)

    raw = str(phone).strip()
    if not raw:
        return {"ok": False, "error": ASK_AGAIN}
    if re.search(r"[A-Za-z]", raw) or re.search(r"[^\d\s\-\.\(\)\+]", raw):
        return {"ok": False, "error": f"{ASK_AGAIN} Use digits only."}

    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+") or raw.startswith("00"):
        intl = digits[2:] if raw.startswith("00") else digits
        if not intl.startswith(str(cc)):
            return {"ok": False, "error": f"That number isn't from {region} (+{cc}). {ASK_AGAIN}"}
        candidate = "+" + intl
    else:
        candidate = digits

    try:
        num = phonenumbers.parse(candidate, region)
    except phonenumbers.NumberParseException:
        return {"ok": False, "error": ASK_AGAIN}

    reason = phonenumbers.is_possible_number_with_reason(num)
    if reason == phonenumbers.ValidationResult.TOO_LONG:
        return {"ok": False, "error": f"That number has too many digits for {region} (+{cc}). {ASK_AGAIN}"}
    if reason == phonenumbers.ValidationResult.TOO_SHORT:
        return {"ok": False, "error": f"That number has too few digits for {region} (+{cc}). {ASK_AGAIN}"}
    if not phonenumbers.is_valid_number(num):
        return {"ok": False, "error": f"That isn't a valid {region} number. {ASK_AGAIN}"}

    national = str(num.national_number)
    junk = fake_reason(national)
    if junk:
        return {"ok": False, "error": f"That number looks invalid ({junk}). {ASK_AGAIN}"}

    ntype = phonenumbers.number_type(num)
    if ntype not in (T.MOBILE, T.FIXED_LINE, T.FIXED_LINE_OR_MOBILE):
        return {"ok": False, "error": f"That looks like a {TYPE_NAMES.get(ntype, 'special')} number. "
                                      f"Please give a mobile or landline number."}
    if kind == "mobile" and ntype == T.FIXED_LINE:
        return {"ok": False, "error": "That is a landline. Please give a mobile number."}
    if kind == "landline" and ntype == T.MOBILE:
        return {"ok": False, "error": "That is a mobile number. Please give a landline number."}

    return {
        "ok": True,
        "e164": phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164),
        "country": region,
        "country_code": cc,
        "national": national,
        "type": TYPE_NAMES[ntype],
    }