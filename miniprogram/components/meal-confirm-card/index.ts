const mealTypes = [
  { value: "breakfast", label: "早餐" },
  { value: "lunch", label: "午餐" },
  { value: "dinner", label: "晚餐" },
  { value: "snack", label: "加餐" },
  { value: "unknown", label: "未确定" }
];

Component({
  properties: {
    action: {
      type: Object,
      value: null
    }
  },

  data: {
    draft: {
      meal_type: "unknown",
      items: []
    },
    mealTypes,
    mealTypeIndex: 4,
    warningFields: [] as string[],
    confidenceText: "--"
  },

  observers: {
    action(action) {
      if (!action) {
        return;
      }
      const draft = {
        meal_type: "unknown",
        items: [],
        ...(action.draft_payload || {})
      };
      const mealTypeIndex = Math.max(
        0,
        mealTypes.findIndex((item) => item.value === draft.meal_type)
      );
      const warningFields = (action.warnings || []).map((warning: { field?: string }) => warning.field).filter(Boolean);
      const confidence = Number(action.confidence ?? draft.confidence);
      this.setData({
        draft,
        mealTypeIndex,
        warningFields,
        confidenceText: Number.isNaN(confidence) ? "--" : `${Math.round(confidence * 100)}%`
      });
    }
  },

  methods: {
    onMealTypeChange(event) {
      const index = Number(event.detail.value);
      this.setData({
        mealTypeIndex: index,
        "draft.meal_type": mealTypes[index].value
      });
    },

    onItemInput(event) {
      const index = Number(event.currentTarget.dataset.index);
      const field = event.currentTarget.dataset.field;
      const value = event.detail.value;
      const items = [...(this.data.draft.items || [])];
      const item = { ...(items[index] || {}) };
      item[field] = numericFields.includes(field) ? parseNullableNumber(value) : value;
      item.user_corrected = true;
      items[index] = item;
      this.setData({
        "draft.items": items
      });
    },

    onAddItem() {
      const items = [...(this.data.draft.items || [])];
      items.push({
        name: "",
        portion_text: "",
        portion_grams: null,
        calories: null,
        protein_g: null,
        carbs_g: null,
        fat_g: null,
        confidence: null,
        user_corrected: true
      });
      this.setData({
        "draft.items": items
      });
    },

    onRemoveItem(event) {
      const index = Number(event.currentTarget.dataset.index);
      const items = [...(this.data.draft.items || [])];
      items.splice(index, 1);
      this.setData({
        "draft.items": items
      });
    },

    onUpdate() {
      this.triggerEvent("update", {
        pending_action_id: this.data.action.pending_action_id,
        draft_payload: this.data.draft
      });
    },

    onConfirm() {
      this.triggerEvent("confirm", {
        pending_action_id: this.data.action.pending_action_id,
        draft_payload: this.data.draft
      });
    },

    onDiscard() {
      this.triggerEvent("discard", {
        pending_action_id: this.data.action.pending_action_id
      });
    }
  }
});

const numericFields = ["portion_grams", "calories", "protein_g", "carbs_g", "fat_g", "confidence"];

function parseNullableNumber(value: string): number | null {
  if (value === "") {
    return null;
  }
  const num = Number(value);
  return Number.isNaN(num) ? null : num;
}

