Component({
  properties: {
    action: {
      type: Object,
      value: null
    }
  },

  data: {
    draft: {},
    warningFields: [] as string[],
    confidenceText: "--"
  },

  observers: {
    action(action) {
      if (!action) {
        return;
      }
      const draft = {
        ...(action.draft_payload || {})
      };
      const warningFields = (action.warnings || []).map((warning: { field?: string }) => warning.field).filter(Boolean);
      const confidence = Number(action.confidence ?? draft.confidence);
      this.setData({
        draft,
        warningFields,
        confidenceText: Number.isNaN(confidence) ? "--" : `${Math.round(confidence * 100)}%`
      });
    }
  },

  methods: {
    onInput(event) {
      const field = event.currentTarget.dataset.field;
      const value = event.detail.value;
      this.setData({
        [`draft.${field}`]: numericFields.includes(field) ? parseNullableNumber(value) : value
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

const numericFields = ["weight_kg", "body_fat_percentage", "bmi", "muscle_mass_kg", "water_percentage", "confidence"];

function parseNullableNumber(value: string): number | null {
  if (value === "") {
    return null;
  }
  const num = Number(value);
  return Number.isNaN(num) ? null : num;
}

