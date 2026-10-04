import json
import random
from vaultproxy.detectors.verhoeff import generate_verhoeff

random.seed(42)

FIRST_NAMES = ["Aarav", "Priya", "Rahul", "Ananya", "Rohan", "Siddharth", "Neha", "Vikram", "Kavya", "Amit"]
LAST_NAMES = ["Sharma", "Verma", "Patel", "Gupta", "Singh", "Kumar", "Joshi", "Chawla", "Reddy", "Mehta"]
DOMAINS = ["example.com", "gmail.com", "company.in", "org.net", "testmail.com"]


def fake_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def fake_email():
    return f"{random.choice(FIRST_NAMES).lower()}{random.randint(10,99)}@{random.choice(DOMAINS)}"


def generate_valid_aadhaar() -> str:
    prefix = str(random.randint(2, 9)) + "".join([str(random.randint(0, 9)) for _ in range(10)])
    check = generate_verhoeff(prefix)
    return prefix + str(check)


def generate_valid_pan() -> str:
    letters = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=3))
    fourth = random.choice(["P", "C", "H", "F", "A", "T", "B", "L", "J", "G"])
    fifth = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    digits = "".join(random.choices("0123456789", k=4))
    last = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return f"{letters}{fourth}{fifth}{digits}{last}"


def generate_dataset():
    samples = []

    upi_handles = ["oksbi", "okaxis", "ybl", "paytm", "okicici"]

    # 1. Clean texts
    for _ in range(15):
        aadhaar = generate_valid_aadhaar()
        pan = generate_valid_pan()
        mobile = f"+91 {random.randint(6,9)}{random.randint(10000,99999)} {random.randint(10000,99999)}"
        upi = f"user{random.randint(100,999)}@{random.choice(upi_handles)}"
        ifsc = f"SBIN00{random.randint(10000,99999)}"
        email = fake_email()
        name = fake_name()

        text = (
            f"Hello, my name is {name}. "
            f"My Aadhaar is {aadhaar} and PAN is {pan}. "
            f"Contact me at {mobile} or email {email}. "
            f"Send money to UPI {upi} at IFSC {ifsc}."
        )

        gold_spans = []
        for val, etype in [
            (aadhaar, "AADHAAR"),
            (pan, "PAN"),
            (mobile, "MOBILE"),
            (email, "EMAIL"),
            (upi, "UPI_ID"),
            (ifsc, "IFSC"),
        ]:
            start = text.find(val)
            if start != -1:
                gold_spans.append({"start": start, "end": start + len(val), "type": etype})

        samples.append({"text": text, "spans": gold_spans})

    # 2. Hinglish chat
    hinglish_templates = [
        "Bhai {name} ko bolo {mobile} pe call kare. PAN number {pan} ready rakhe.",
        "Mera Aadhaar {aadhaar} verify nahi ho raha, send email to {email}",
        "UPI ID {upi} pe payment kar do, IFSC is {ifsc}.",
    ]

    for _ in range(15):
        aadhaar = generate_valid_aadhaar()
        pan = generate_valid_pan()
        mobile = f"98765{random.randint(10000,99999)}"
        upi = f"raj{random.randint(100,999)}@ybl"
        ifsc = f"HDFC00{random.randint(10000,99999)}"
        email = fake_email()
        name = fake_name()

        tmpl = random.choice(hinglish_templates)
        text = tmpl.format(name=name, pan=pan, aadhaar=aadhaar, email=email, upi=upi, ifsc=ifsc, mobile=mobile)

        gold_spans = []
        for val, etype in [
            (aadhaar, "AADHAAR"),
            (pan, "PAN"),
            (mobile, "MOBILE"),
            (email, "EMAIL"),
            (upi, "UPI_ID"),
            (ifsc, "IFSC"),
        ]:
            start = text.find(val)
            if start != -1:
                gold_spans.append({"start": start, "end": start + len(val), "type": etype})

        samples.append({"text": text, "spans": gold_spans})

    # 3. Secrets & tricky negatives
    secrets_samples = [
        ("AWS credentials leak: AKIAIOSFODNN7EXAMPLE in log file.", [("AKIAIOSFODNN7EXAMPLE", "SECRET")]),
        ("GitHub PAT found: github_pat_11AAAAAAA0123456789012_abcdefghijklmnopqrstuvwxyz", [("github_pat_11AAAAAAA0123456789012_abcdefghijklmnopqrstuvwxyz", "SECRET")]),
        ("Order ID 123456789012 and invalid check 367598341209 should be ignored.", []),
        ("Invalid PAN ABCXX1234F and bad IFSC SBIN1001234 should be ignored.", []),
        ("Normal email user@example.com is not UPI.", [("user@example.com", "EMAIL")]),
    ]

    for text, entities in secrets_samples * 2:
        gold_spans = []
        for val, etype in entities:
            start = text.find(val)
            if start != -1:
                gold_spans.append({"start": start, "end": start + len(val), "type": etype})
        samples.append({"text": text, "spans": gold_spans})

    with open("bench/dataset.json", "w", encoding="utf-8") as f:
        json.dump(samples, f, indent=2)

    print(f"Generated {len(samples)} benchmark samples in bench/dataset.json")


if __name__ == "__main__":
    generate_dataset()
