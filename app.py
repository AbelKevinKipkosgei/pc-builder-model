import streamlit as st
import pandas as pd

st.set_page_config(page_title="PC Builder", layout="wide")

DATA_DIR = "data/"

# ---------------------------------------------------------------------------
# DATA LOADING
# ---------------------------------------------------------------------------

@st.cache_data
def load_data():
    cpu = pd.read_csv(DATA_DIR + "cpu_clean_full.csv")
    mobo = pd.read_csv(DATA_DIR + "motherboard_clean_full.csv")
    ram = pd.read_csv(DATA_DIR + "memory_clean_full.csv")
    gpu = pd.read_csv(DATA_DIR + "video-card_clean_full.csv")
    psu = pd.read_csv(DATA_DIR + "power-supply_clean_full.csv")
    case = pd.read_csv(DATA_DIR + "case_clean_full.csv")

    cpu_p = pd.read_csv(DATA_DIR + "cpu_clean_priced.csv")
    mobo_p = pd.read_csv(DATA_DIR + "motherboard_clean_priced.csv")
    ram_p = pd.read_csv(DATA_DIR + "memory_clean_priced.csv")
    gpu_p = pd.read_csv(DATA_DIR + "video-card_clean_priced.csv")
    psu_p = pd.read_csv(DATA_DIR + "power-supply_clean_priced.csv")
    case_p = pd.read_csv(DATA_DIR + "case_clean_priced.csv")

    return {
        "cpu": cpu, "mobo": mobo, "ram": ram, "gpu": gpu, "psu": psu, "case": case,
        "cpu_p": cpu_p, "mobo_p": mobo_p, "ram_p": ram_p, "gpu_p": gpu_p, "psu_p": psu_p, "case_p": case_p,
    }


# ---------------------------------------------------------------------------
# COMPATIBILITY CHECK FUNCTIONS  (ported from Colab, unchanged logic)
# ---------------------------------------------------------------------------

FORM_FACTOR_RANK = {"Mini ITX": 1, "MicroATX": 2, "ATX": 3}


def normalize_form_factor(value):
    return value.replace(" ", "").strip()


def check_cpu_motherboard(cpu, mobo):
    if cpu["socket"] == mobo["primary_socket"]:
        return True, f"✓ {cpu['socket']} matches motherboard socket"
    return False, f"✗ CPU socket ({cpu['socket']}) does not match motherboard socket ({mobo['primary_socket']})"


def check_ram_motherboard(ram, mobo):
    if pd.isnull(mobo["ram_type"]):
        return False, "✗ Motherboard has an integrated CPU — no upgradable RAM slot info available"
    if ram["ram_type"] == mobo["ram_type"]:
        return True, f"✓ {ram['ram_type']} matches motherboard"
    return False, f"✗ RAM type ({ram['ram_type']}) does not match motherboard ({mobo['ram_type']})"


def check_ram_capacity(ram, mobo):
    issues = []
    if ram["capacity_gb"] > mobo["max_memory"]:
        issues.append(f"RAM capacity ({ram['capacity_gb']}GB) exceeds motherboard max ({mobo['max_memory']}GB)")
    if ram["num_sticks"] > mobo["memory_slots"]:
        issues.append(f"RAM needs {ram['num_sticks']} slots, motherboard only has {mobo['memory_slots']}")
    if issues:
        return False, "✗ " + "; ".join(issues)
    return True, "✓ RAM capacity and slot count fit"


def check_gpu_case(gpu, case):
    if gpu["length"] <= case["estimated_max_gpu_length"]:
        note = " (estimated)" if case.get("is_estimated_gpu_clearance") else ""
        return True, f"✓ GPU length ({gpu['length']}mm) fits case clearance{note}"
    return False, f"✗ GPU length ({gpu['length']}mm) exceeds estimated case clearance ({case['estimated_max_gpu_length']}mm)"


def check_motherboard_case(mobo, case):
    mobo_ff = normalize_form_factor(mobo["form_factor"])
    case_ff = normalize_form_factor(case["form_factor_family"]) if pd.notnull(case["form_factor_family"]) else None

    if case_ff is None or mobo_ff not in FORM_FACTOR_RANK or case_ff not in FORM_FACTOR_RANK:
        return False, f"✗ Could not determine form factor compatibility ({mobo['form_factor']} vs {case['type']})"

    if FORM_FACTOR_RANK[mobo_ff] <= FORM_FACTOR_RANK[case_ff]:
        return True, f"✓ {mobo['form_factor']} fits in {case['type']}"
    return False, f"✗ Motherboard ({mobo['form_factor']}) is too large for case ({case['type']})"


def check_psu_wattage(cpu, gpu, psu, headroom_pct=20):
    base_system_draw = 100
    total_draw = cpu["tdp"] + gpu["estimated_tdp"] + base_system_draw
    required_wattage = total_draw * (1 + headroom_pct / 100)

    if psu["wattage"] >= required_wattage:
        return True, f"✓ PSU ({psu['wattage']}W) covers estimated draw ({total_draw:.0f}W + {headroom_pct}% headroom = {required_wattage:.0f}W)"
    return False, f"✗ PSU ({psu['wattage']}W) insufficient — estimated draw needs {required_wattage:.0f}W ({total_draw:.0f}W + {headroom_pct}% headroom)"


def check_full_build(cpu, mobo, ram, gpu, psu, case):
    checks = [
        ("CPU ↔ Motherboard", check_cpu_motherboard(cpu, mobo)),
        ("RAM ↔ Motherboard (type)", check_ram_motherboard(ram, mobo)),
        ("RAM ↔ Motherboard (capacity)", check_ram_capacity(ram, mobo)),
        ("GPU ↔ Case", check_gpu_case(gpu, case)),
        ("Motherboard ↔ Case", check_motherboard_case(mobo, case)),
        ("PSU Wattage", check_psu_wattage(cpu, gpu, psu)),
    ]
    results = [{"check": label, "passed": passed, "message": message} for label, (passed, message) in checks]
    return {"overall_compatible": all(r["passed"] for r in results), "details": results}


# ---------------------------------------------------------------------------
# SCORING FUNCTIONS
# ---------------------------------------------------------------------------

def score_cpu(row):
    return row["core_count"] * row["boost_clock"]


def score_gpu(row):
    return row["memory"] * 10 + (row["boost_clock"] if pd.notnull(row["boost_clock"]) else 0)


def score_ram(row):
    return row["capacity_gb"] * row["speed_mhz"]


def score_motherboard(row):
    return row["max_memory"] + row["memory_slots"] * 10


def score_psu(row):
    return row["wattage"]


def score_case(row):
    return row["estimated_max_gpu_length"]


# ---------------------------------------------------------------------------
# RECOMMENDATION ENGINE
# ---------------------------------------------------------------------------

USE_CASE_BUDGET_SPLIT = {
    "Gaming": {"cpu": 0.20, "motherboard": 0.10, "ram": 0.10, "gpu": 0.40, "psu": 0.10, "case": 0.10},
    "Video Editing": {"cpu": 0.30, "motherboard": 0.10, "ram": 0.20, "gpu": 0.25, "psu": 0.10, "case": 0.05},
    "Office/Browsing": {"cpu": 0.25, "motherboard": 0.15, "ram": 0.15, "gpu": 0.10, "psu": 0.15, "case": 0.20},
}


def best_in_budget(df_priced, sub_budget, score_func, filter_mask=None, min_spend_pct=0.6):
    mask = (df_priced["price"] <= sub_budget) & (df_priced["price"] >= sub_budget * min_spend_pct)
    if filter_mask is not None:
        mask = mask & filter_mask
    candidates = df_priced[mask].copy()

    if candidates.empty:
        mask = df_priced["price"] <= sub_budget
        if filter_mask is not None:
            mask = mask & filter_mask
        candidates = df_priced[mask].copy()

    if candidates.empty:
        return None
    candidates["score"] = candidates.apply(score_func, axis=1)
    return candidates.sort_values("score", ascending=False).iloc[0]


def generate_build(data, total_budget, use_case):
    split = USE_CASE_BUDGET_SPLIT[use_case]

    cpu_budget = total_budget * split["cpu"]
    cpu = best_in_budget(data["cpu_p"], cpu_budget, score_cpu, min_spend_pct=0.3)
    if cpu is None:
        return {"error": f"No CPU found within ${cpu_budget:.0f} budget allocation. Try increasing your total budget."}

    mobo_budget = total_budget * split["motherboard"] + (cpu_budget - cpu["price"])
    mobo_mask = data["mobo_p"]["primary_socket"] == cpu["socket"]
    mobo = best_in_budget(data["mobo_p"], mobo_budget, score_motherboard, filter_mask=mobo_mask, min_spend_pct=0.3)
    if mobo is None:
        return {"error": f"Budget too tight: after CPU (${cpu['price']:.0f}), only ${mobo_budget:.0f} left for a {cpu['socket']} motherboard. Try a budget of at least ${total_budget + 100:.0f}."}

    ram_budget = total_budget * split["ram"] + (mobo_budget - mobo["price"])
    ram_mask = (
        (data["ram_p"]["ram_type"] == mobo["ram_type"]) &
        (data["ram_p"]["capacity_gb"] <= mobo["max_memory"]) &
        (data["ram_p"]["num_sticks"] <= mobo["memory_slots"])
    )
    ram = best_in_budget(data["ram_p"], ram_budget, score_ram, filter_mask=ram_mask)
    if ram is None:
        return {"error": f"No RAM found matching {mobo['ram_type']} within budget allocation."}

    gpu_budget = total_budget * split["gpu"] + (ram_budget - ram["price"])
    gpu = best_in_budget(data["gpu_p"], gpu_budget, score_gpu)
    if gpu is None:
        return {"error": "No GPU found within budget allocation."}

    case_budget = total_budget * split["case"] + (gpu_budget - gpu["price"])
    case_mask = data["case_p"]["estimated_max_gpu_length"] >= gpu["length"]
    case = best_in_budget(data["case_p"], case_budget, score_case, filter_mask=case_mask)
    if case is None:
        return {"error": "No case found with enough GPU clearance within budget allocation."}

    required_watts = (cpu["tdp"] + gpu["estimated_tdp"] + 100) * 1.2
    psu_budget = total_budget * split["psu"] + (case_budget - case["price"])
    psu_mask = data["psu_p"]["wattage"] >= required_watts
    psu = best_in_budget(data["psu_p"], psu_budget, score_psu, filter_mask=psu_mask)
    if psu is None:
        return {"error": f"No PSU found with {required_watts:.0f}W+ within budget allocation."}

    total_cost = cpu["price"] + mobo["price"] + ram["price"] + gpu["price"] + case["price"] + psu["price"]

    return {
        "cpu": cpu, "motherboard": mobo, "ram": ram,
        "gpu": gpu, "case": case, "psu": psu,
        "total_cost": total_cost, "budget": total_budget,
    }


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.title("🖥️ PC Parts Compatibility & Build Recommender")

data = load_data()

mode = st.radio("Mode", ["Auto-generate a build", "Build your own"], horizontal=True)

# ---------------------------------------------------------------------------
# MODE 1: AUTO-GENERATE
# ---------------------------------------------------------------------------

if mode == "Auto-generate a build":
    with st.sidebar:
        st.header("Your build")
        use_case = st.selectbox("Use case", list(USE_CASE_BUDGET_SPLIT.keys()))
        budget = st.slider("Budget ($)", min_value=400, max_value=4000, value=1200, step=50)
        generate_clicked = st.button("Generate build", type="primary")

    if generate_clicked:
        build = generate_build(data, budget, use_case)

        if "error" in build:
            st.error(build["error"])
        else:
            check = check_full_build(
                build["cpu"], build["motherboard"], build["ram"],
                build["gpu"], build["psu"], build["case"]
            )

            col1, col2, col3 = st.columns(3)
            col1.metric("Estimated total", f"${build['total_cost']:.2f}")
            col2.metric("Compatibility", "All good ✓" if check["overall_compatible"] else "Issues found ✗")
            col3.metric("Budget", f"${budget}")

            st.subheader("Recommended parts")
            parts_table = pd.DataFrame([
                {"Component": "CPU", "Part": build["cpu"]["name"], "Price": f"${build['cpu']['price']:.2f}"},
                {"Component": "Motherboard", "Part": build["motherboard"]["name"], "Price": f"${build['motherboard']['price']:.2f}"},
                {"Component": "RAM", "Part": build["ram"]["name"], "Price": f"${build['ram']['price']:.2f}"},
                {"Component": "GPU", "Part": build["gpu"]["name"], "Price": f"${build['gpu']['price']:.2f}"},
                {"Component": "Case", "Part": build["case"]["name"], "Price": f"${build['case']['price']:.2f}"},
                {"Component": "PSU", "Part": build["psu"]["name"], "Price": f"${build['psu']['price']:.2f}"},
            ])
            st.table(parts_table)

            st.subheader("Compatibility checks")
            for r in check["details"]:
                if r["passed"]:
                    st.success(r["message"])
                else:
                    st.error(r["message"])
    else:
        st.info("Set your budget and use case in the sidebar, then click **Generate build**.")

# ---------------------------------------------------------------------------
# MODE 2: BUILD YOUR OWN (cascading filtered dropdowns)
# ---------------------------------------------------------------------------

else:
    st.subheader("Pick your parts")
    st.caption("Each dropdown filters to only show options compatible with what you've already picked.")

    col1, col2 = st.columns(2)

    # --- CPU: no filtering, the starting point ---
    with col1:
        cpu_options = data["cpu"].sort_values("name")
        cpu_name = st.selectbox("CPU", cpu_options["name"].tolist())
        cpu = cpu_options[cpu_options["name"] == cpu_name].iloc[0]

    # --- Motherboard: filtered to CPU's socket ---
    with col2:
        mobo_candidates = data["mobo"][data["mobo"]["primary_socket"] == cpu["socket"]].sort_values("name")
        if mobo_candidates.empty:
            st.warning(f"No motherboards found for socket {cpu['socket']}.")
            mobo = None
        else:
            mobo_name = st.selectbox(f"Motherboard (socket: {cpu['socket']})", mobo_candidates["name"].tolist())
            mobo = mobo_candidates[mobo_candidates["name"] == mobo_name].iloc[0]

    col3, col4 = st.columns(2)

    # --- RAM: filtered to motherboard's ram_type and capacity/slot limits ---
    with col3:
        if mobo is not None and pd.notnull(mobo["ram_type"]):
            ram_candidates = data["ram"][
                (data["ram"]["ram_type"] == mobo["ram_type"]) &
                (data["ram"]["capacity_gb"] <= mobo["max_memory"]) &
                (data["ram"]["num_sticks"] <= mobo["memory_slots"])
            ].sort_values("name")
            if ram_candidates.empty:
                st.warning(f"No {mobo['ram_type']} kits found that fit this motherboard's limits.")
                ram = None
            else:
                ram_name = st.selectbox(f"RAM (type: {mobo['ram_type']})", ram_candidates["name"].tolist())
                ram = ram_candidates[ram_candidates["name"] == ram_name].iloc[0]
        else:
            st.warning("Select a compatible motherboard first.")
            ram = None

    # --- GPU: no filtering yet, constrains case afterward ---
    with col4:
        gpu_options = data["gpu"].sort_values(["chipset", "name"]).reset_index(drop=True)
        gpu_display_labels = gpu_options["chipset"] + " — " + gpu_options["name"]
        gpu_choice = st.selectbox("GPU", gpu_display_labels.tolist())
        gpu = gpu_options[gpu_display_labels == gpu_choice].iloc[0]

    col5, col6 = st.columns(2)

    # --- Case: filtered to fit GPU length AND motherboard form factor ---
    with col5:
        if mobo is not None:
            mobo_ff = normalize_form_factor(mobo["form_factor"])
            case_candidates = data["case"][
                (data["case"]["estimated_max_gpu_length"] >= gpu["length"]) &
                (data["case"]["form_factor_family"].apply(
                    lambda x: pd.notnull(x)
                    and normalize_form_factor(x) in FORM_FACTOR_RANK
                    and mobo_ff in FORM_FACTOR_RANK
                    and FORM_FACTOR_RANK[mobo_ff] <= FORM_FACTOR_RANK[normalize_form_factor(x)]
                ))
            ].sort_values("name")
            if case_candidates.empty:
                st.warning("No cases found that fit both this GPU and this motherboard.")
                case = None
            else:
                case_name = st.selectbox("Case", case_candidates["name"].tolist())
                case = case_candidates[case_candidates["name"] == case_name].iloc[0]
        else:
            st.warning("Select a compatible motherboard first.")
            case = None

    # --- PSU: filtered to required wattage for CPU + GPU ---
    with col6:
        required_watts = (cpu["tdp"] + gpu["estimated_tdp"] + 100) * 1.2
        psu_candidates = data["psu"][data["psu"]["wattage"] >= required_watts].sort_values("name")
        if psu_candidates.empty:
            st.warning(f"No PSUs found with at least {required_watts:.0f}W.")
            psu = None
        else:
            psu_name = st.selectbox(f"PSU (min: {required_watts:.0f}W)", psu_candidates["name"].tolist())
            psu = psu_candidates[psu_candidates["name"] == psu_name].iloc[0]

    st.divider()

    if st.button("Check full build", type="primary"):
        if mobo is None or ram is None or case is None or psu is None:
            st.error("Please resolve the warnings above before checking the full build.")
        else:
            check = check_full_build(cpu, mobo, ram, gpu, psu, case)

            total_cost = sum(
                p["price"] for p in (cpu, mobo, ram, gpu, case, psu) if pd.notnull(p["price"])
            )
            missing_price = any(pd.isnull(p["price"]) for p in (cpu, mobo, ram, gpu, case, psu))

            col1, col2 = st.columns(2)
            col1.metric("Estimated total", f"${total_cost:.2f}" + (" *" if missing_price else ""))
            col2.metric("Compatibility", "All good ✓" if check["overall_compatible"] else "Issues found ✗")
            if missing_price:
                st.caption("* One or more selected parts has no listed price; total is a partial estimate.")

            st.subheader("Compatibility checks")
            for r in check["details"]:
                if r["passed"]:
                    st.success(r["message"])
                else:
                    st.error(r["message"])
