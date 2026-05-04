import { mealTypeLabels, numberText } from "../../utils/format";

Component({
  properties: {
    action: {
      type: Object,
      value: null,
      observer(this: any) {
        this.refreshCard();
      }
    }
  },

  data: {
    card: null as any
  },

  lifetimes: {
    attached(this: any) {
      this.refreshCard();
    }
  },

  methods: {
    refreshCard(this: any) {
      const action = this.properties.action as any;
      if (!action) {
        this.setData({ card: null });
        return;
      }

      const payload = action.draft_payload || {};
      const warnings = action.warnings || [];
      const warningFields = warnings.map((item: any) => item.field).filter(Boolean);

      if (action.type === "create_meal_record") {
        const items = (payload.items || []).map((item: any) => ({
          ...item,
          caloriesText: numberText(item.calories, " kcal"),
          proteinText: numberText(item.protein_g, "g"),
          carbsText: numberText(item.carbs_g, "g"),
          fatText: numberText(item.fat_g, "g"),
          lowConfidence: (item.confidence || action.confidence || 1) < 0.8
        }));
        const totalCalories = payload.total_calories ?? items.reduce((sum: number, item: any) => sum + (Number(item.calories) || 0), 0);
        const totalProtein = payload.total_protein_g ?? items.reduce((sum: number, item: any) => sum + (Number(item.protein_g) || 0), 0);
        const totalCarbs = payload.total_carbs_g ?? items.reduce((sum: number, item: any) => sum + (Number(item.carbs_g) || 0), 0);
        const totalFat = payload.total_fat_g ?? items.reduce((sum: number, item: any) => sum + (Number(item.fat_g) || 0), 0);
        this.setData({
          card: {
            kind: "meal",
            title: "餐食记录",
            mealType: mealTypeLabels[payload.meal_type || "unknown"] || "餐食",
            items,
            totals: [
              { label: "总热量", value: numberText(totalCalories, " kcal") },
              { label: "蛋白质", value: numberText(Number(totalProtein.toFixed ? totalProtein.toFixed(1) : totalProtein), "g") },
              { label: "碳水", value: numberText(Number(totalCarbs.toFixed ? totalCarbs.toFixed(1) : totalCarbs), "g") },
              { label: "脂肪", value: numberText(Number(totalFat.toFixed ? totalFat.toFixed(1) : totalFat), "g") }
            ],
            hasWarnings: warningFields.length > 0 || (action.confidence || 1) < 0.8
          }
        });
        return;
      }

      if (action.type === "create_body_metric_record") {
        this.setData({
          card: {
            kind: "body",
            title: "身体指标",
            fields: [
              { label: "体重", value: numberText(payload.weight_kg, " kg") },
              { label: "体脂率", value: numberText(payload.body_fat_percentage, "%") },
              { label: "BMI", value: numberText(payload.bmi) },
              { label: "记录时间", value: payload.recorded_at ? "刚刚" : "待确认" }
            ],
            hasWarnings: warningFields.length > 0 || (action.confidence || 1) < 0.8
          }
        });
        return;
      }

      this.setData({
        card: {
          kind: "unknown",
          title: "待确认动作",
          hasWarnings: warningFields.length > 0
        }
      });
    },

    onConfirm(this: any) {
      const action = this.properties.action as any;
      this.triggerEvent("confirm", { pendingActionId: action.pending_action_id });
    },

    onEdit(this: any) {
      const action = this.properties.action as any;
      this.triggerEvent("edit", { pendingActionId: action.pending_action_id, action });
    },

    onDiscard(this: any) {
      const action = this.properties.action as any;
      this.triggerEvent("discard", { pendingActionId: action.pending_action_id });
    }
  }
});
