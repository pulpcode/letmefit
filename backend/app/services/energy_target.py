from dataclasses import dataclass
from typing import Any

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

GOAL_DEFICIT_KCAL = {
    "fat_loss": -500,
    "muscle_gain": 300,
    "maintenance": 0,
    "fitness": 0,
}

DEFAULT_MACROS_STRATEGY = {
    "fat_loss": "high_protein",
    "muscle_gain": "balanced",
    "maintenance": "balanced",
    "fitness": "balanced",
}

REQUIRED_PROFILE_FIELDS = ("age", "sex", "height_cm", "current_weight_kg", "activity_level")
SUPPORTED_SEXES = {"male", "female"}


@dataclass
class EnergyTargetInputs:
    age: int
    sex: str
    height_cm: float
    weight_kg: float
    activity_level: str
    goal_type: str
    deficit_kcal_per_day: int
    macros_strategy: str
    formula: str


@dataclass
class EnergyTarget:
    bmr: int
    tdee: int
    target_calories: int
    deficit_or_surplus_kcal: int
    macros_target: dict[str, int]
    formula: str
    activity_multiplier: float
    macros_strategy: str
    strategy_text: str
    inputs_used: dict[str, Any]


def compute_energy_target(
    profile: dict[str, Any] | None,
    overrides: dict[str, Any] | None = None,
) -> tuple[EnergyTarget | None, list[dict[str, str]]]:
    overrides = overrides or {}
    warnings: list[dict[str, str]] = []

    if not profile:
        warnings.append({"field": "energy_target", "reason": "profile_missing"})
        return None, warnings

    inputs, missing = _resolve_inputs(profile, overrides)
    if inputs is None:
        warnings.append(
            {
                "field": "energy_target",
                "reason": "profile_incomplete",
                "missing": ",".join(missing),
            }
        )
        return None, warnings

    bmr = _bmr_mifflin(inputs)
    multiplier = ACTIVITY_MULTIPLIERS[inputs.activity_level]
    tdee = bmr * multiplier
    target_calories = tdee + inputs.deficit_kcal_per_day
    macros = _macros(inputs, target_calories)
    strategy_text = _strategy_text(inputs)

    return (
        EnergyTarget(
            bmr=int(round(bmr)),
            tdee=int(round(tdee)),
            target_calories=int(round(target_calories)),
            deficit_or_surplus_kcal=inputs.deficit_kcal_per_day,
            macros_target=macros,
            formula="mifflin_st_jeor",
            activity_multiplier=multiplier,
            macros_strategy=inputs.macros_strategy,
            strategy_text=strategy_text,
            inputs_used={
                "age": inputs.age,
                "sex": inputs.sex,
                "height_cm": inputs.height_cm,
                "weight_kg": inputs.weight_kg,
                "activity_level": inputs.activity_level,
                "goal_type": inputs.goal_type,
                "deficit_kcal_per_day": inputs.deficit_kcal_per_day,
                "macros_strategy": inputs.macros_strategy,
                "formula": inputs.formula,
            },
        ),
        warnings,
    )


def energy_target_to_dict(target: EnergyTarget | None) -> dict[str, Any] | None:
    if target is None:
        return None
    return {
        "bmr": target.bmr,
        "tdee": target.tdee,
        "target_calories": target.target_calories,
        "deficit_or_surplus_kcal": target.deficit_or_surplus_kcal,
        "macros_target": target.macros_target,
        "formula": target.formula,
        "activity_multiplier": target.activity_multiplier,
        "macros_strategy": target.macros_strategy,
        "strategy_text": target.strategy_text,
        "inputs_used": target.inputs_used,
    }


def _resolve_inputs(
    profile: dict[str, Any],
    overrides: dict[str, Any],
) -> tuple[EnergyTargetInputs | None, list[str]]:
    weight = overrides.get("weight_kg") or profile.get("current_weight_kg")
    activity = overrides.get("activity_level") or profile.get("activity_level")
    goal = overrides.get("goal_type") or profile.get("goal_type") or "maintenance"

    sex = profile.get("sex")
    age = profile.get("age")
    height = profile.get("height_cm")

    missing: list[str] = []
    if not isinstance(age, int) or age <= 0:
        missing.append("age")
    if sex not in SUPPORTED_SEXES:
        missing.append("sex")
    if not isinstance(height, (int, float)) or height <= 0:
        missing.append("height_cm")
    if not isinstance(weight, (int, float)) or weight <= 0:
        missing.append("weight_kg")
    if activity not in ACTIVITY_MULTIPLIERS:
        missing.append("activity_level")
    if missing:
        return None, missing

    deficit = overrides.get("deficit_kcal_per_day")
    if deficit is None:
        deficit = GOAL_DEFICIT_KCAL.get(goal, 0)

    macros_strategy = overrides.get("macros_strategy") or DEFAULT_MACROS_STRATEGY.get(goal, "balanced")

    return (
        EnergyTargetInputs(
            age=int(age),
            sex=str(sex),
            height_cm=float(height),
            weight_kg=float(weight),
            activity_level=str(activity),
            goal_type=str(goal),
            deficit_kcal_per_day=int(deficit),
            macros_strategy=str(macros_strategy),
            formula="mifflin",
        ),
        [],
    )


def _bmr_mifflin(inputs: EnergyTargetInputs) -> float:
    base = 10 * inputs.weight_kg + 6.25 * inputs.height_cm - 5 * inputs.age
    return base + (5 if inputs.sex == "male" else -161)


def _macros(inputs: EnergyTargetInputs, target_calories: float) -> dict[str, int]:
    if inputs.macros_strategy == "high_protein":
        protein_per_kg = 2.0
        fat_pct = 0.25
        carbs_min_g = 0
    elif inputs.macros_strategy == "keto":
        protein_per_kg = 1.6
        fat_pct = 0.70
        carbs_min_g = 20
    else:  # balanced
        protein_per_kg = 1.6
        fat_pct = 0.30
        carbs_min_g = 0

    protein_g = protein_per_kg * inputs.weight_kg
    fat_g = (target_calories * fat_pct) / 9
    carbs_kcal = target_calories - protein_g * 4 - fat_g * 9
    carbs_g = max(carbs_min_g, carbs_kcal / 4)

    return {
        "protein_g": int(round(protein_g)),
        "carbs_g": int(round(carbs_g)),
        "fat_g": int(round(fat_g)),
    }


def _strategy_text(inputs: EnergyTargetInputs) -> str:
    goal_label = {
        "fat_loss": "减脂",
        "muscle_gain": "增肌",
        "maintenance": "维持",
        "fitness": "塑形",
    }.get(inputs.goal_type, inputs.goal_type)
    strategy_label = {
        "high_protein": "高蛋白",
        "balanced": "均衡",
        "keto": "生酮",
    }.get(inputs.macros_strategy, inputs.macros_strategy)
    return f"{goal_label}（{strategy_label}）：每日热量赤字 {inputs.deficit_kcal_per_day:+d} kcal"
