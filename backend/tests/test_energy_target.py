from app.services.energy_target import compute_energy_target, energy_target_to_dict


def _profile(**overrides):
    base = {
        "age": 30,
        "sex": "male",
        "height_cm": 175,
        "current_weight_kg": 75,
        "target_weight_kg": 70,
        "activity_level": "moderate",
        "goal_type": "fat_loss",
        "profile_completed": True,
    }
    base.update(overrides)
    return base


def test_compute_energy_target_male_fat_loss_matches_mifflin() -> None:
    target, warnings = compute_energy_target(_profile())

    assert warnings == []
    # Mifflin male: 10*75 + 6.25*175 - 5*30 + 5 = 750 + 1093.75 - 150 + 5 = 1698.75
    assert target.bmr == 1699
    # TDEE = 1698.75 * 1.55 = 2633.0625 → 2633
    assert target.tdee == 2633
    # target_calories = 2633 - 500 = 2133
    assert target.target_calories == 2133
    assert target.deficit_or_surplus_kcal == -500
    # high_protein for fat_loss: protein 2g/kg = 150g, fat 25% of 2133 / 9 ≈ 59g, carbs balance
    assert target.macros_target["protein_g"] == 150
    assert target.macros_target["fat_g"] in (59, 60)
    assert target.macros_strategy == "high_protein"
    assert target.formula == "mifflin_st_jeor"


def test_compute_energy_target_female_maintenance_matches_mifflin() -> None:
    target, warnings = compute_energy_target(
        _profile(sex="female", goal_type="maintenance", current_weight_kg=60, height_cm=165, age=28),
    )

    assert warnings == []
    # Mifflin female: 10*60 + 6.25*165 - 5*28 - 161 = 600 + 1031.25 - 140 - 161 = 1330.25
    assert target.bmr == 1330
    # TDEE = 1330.25 * 1.55 = 2061.8875 → 2062
    assert target.tdee == 2062
    assert target.target_calories == 2062
    assert target.deficit_or_surplus_kcal == 0
    # balanced for maintenance: protein 1.6g/kg = 96g, fat 30% of 2062 / 9 ≈ 69g
    assert target.macros_target["protein_g"] == 96
    assert target.macros_target["fat_g"] in (68, 69)


def test_compute_energy_target_muscle_gain_uses_surplus() -> None:
    target, _warnings = compute_energy_target(_profile(goal_type="muscle_gain"))

    assert target.deficit_or_surplus_kcal == 300
    assert target.target_calories == target.tdee + 300


def test_compute_energy_target_returns_warning_when_profile_incomplete() -> None:
    target, warnings = compute_energy_target(_profile(activity_level=None, age=None))

    assert target is None
    assert warnings[0]["field"] == "energy_target"
    assert warnings[0]["reason"] == "profile_incomplete"
    assert "age" in warnings[0]["missing"]
    assert "activity_level" in warnings[0]["missing"]


def test_compute_energy_target_returns_warning_when_profile_missing() -> None:
    target, warnings = compute_energy_target(None)

    assert target is None
    assert warnings == [{"field": "energy_target", "reason": "profile_missing"}]


def test_compute_energy_target_rejects_unsupported_sex() -> None:
    target, warnings = compute_energy_target(_profile(sex="other"))

    assert target is None
    assert warnings[0]["reason"] == "profile_incomplete"
    assert "sex" in warnings[0]["missing"]


def test_compute_energy_target_overrides_take_precedence() -> None:
    target, _ = compute_energy_target(
        _profile(goal_type="maintenance"),
        overrides={"deficit_kcal_per_day": -750, "macros_strategy": "balanced"},
    )

    assert target.deficit_or_surplus_kcal == -750
    assert target.macros_strategy == "balanced"
    assert target.target_calories == target.tdee - 750


def test_energy_target_to_dict_round_trips_required_keys() -> None:
    target, _ = compute_energy_target(_profile())

    payload = energy_target_to_dict(target)

    assert set(payload.keys()) >= {
        "bmr",
        "tdee",
        "target_calories",
        "deficit_or_surplus_kcal",
        "macros_target",
        "formula",
        "activity_multiplier",
        "macros_strategy",
        "strategy_text",
        "inputs_used",
    }
    assert energy_target_to_dict(None) is None
