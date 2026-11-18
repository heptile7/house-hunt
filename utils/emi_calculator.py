def calculate_emi(principal: float, annual_rate: float, tenure_years: int) -> dict:
    monthly_rate = annual_rate / 100 / 12
    n = tenure_years * 12
    if monthly_rate == 0:
        emi = principal / n
    else:
        emi = principal * monthly_rate * (1 + monthly_rate) ** n / ((1 + monthly_rate) ** n - 1)
    total_payment = emi * n
    total_interest = total_payment - principal
    return {
        "emi": round(emi),
        "total_payment": round(total_payment),
        "total_interest": round(total_interest),
        "principal": round(principal),
        "months": n,
    }


def estimate_stamp_duty(price: int, state: str = "Karnataka") -> dict:
    rates = {
        "Karnataka": {"stamp": 5.0, "registration": 1.0},
        "Maharashtra": {"stamp": 5.0, "registration": 1.0},
        "Delhi": {"stamp": 6.0, "registration": 1.0},
        "Tamil Nadu": {"stamp": 7.0, "registration": 1.0},
        "Telangana": {"stamp": 5.0, "registration": 0.5},
        "West Bengal": {"stamp": 6.0, "registration": 1.0},
        "Gujarat": {"stamp": 4.9, "registration": 1.0},
        "Rajasthan": {"stamp": 6.0, "registration": 1.0},
        "Uttar Pradesh": {"stamp": 7.0, "registration": 1.0},
        "Kerala": {"stamp": 8.0, "registration": 2.0},
        "Madhya Pradesh": {"stamp": 7.5, "registration": 3.0},
    }
    r = rates.get(state, {"stamp": 5.0, "registration": 1.0})
    stamp = round(price * r["stamp"] / 100)
    reg = round(price * r["registration"] / 100)
    return {
        "stamp_duty": stamp,
        "registration": reg,
        "total_charges": stamp + reg,
        "stamp_rate": r["stamp"],
        "reg_rate": r["registration"],
    }


def estimate_gst(price: int, under_construction: bool = False) -> int:
    """GST applies only to under-construction property: 1% if affordable (< ₹45L), else 5%.
    Ready-to-move / resale property attracts no GST."""
    if not under_construction:
        return 0
    return round(price * (0.01 if price < 4_500_000 else 0.05))


def total_cost_breakdown(
    price: int, loan_pct: float, rate: float, tenure: int, state: str, under_construction: bool = False
) -> dict:
    down_payment = round(price * (1 - loan_pct / 100))
    principal = price - down_payment
    emi_data = calculate_emi(principal, rate, tenure)
    stamp_data = estimate_stamp_duty(price, state)
    gst = estimate_gst(price, under_construction)
    return {
        "property_price": price,
        "down_payment": down_payment,
        "loan_amount": principal,
        "gst": gst,
        **stamp_data,
        **emi_data,
        "move_in_cost": down_payment + stamp_data["total_charges"] + gst,
    }


def format_inr(amount: int) -> str:
    if amount >= 1_00_00_000:
        return f"₹{amount / 1_00_00_000:.2f} Cr"
    elif amount >= 1_00_000:
        return f"₹{amount / 1_00_000:.2f} L"
    return f"₹{amount:,}"
