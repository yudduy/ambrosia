import { useEffect, useState } from "react";
import { Button, Select, SelectItem, TextArea, TextInput } from "@carbon/react";
import { Close } from "@carbon/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Profile } from "../lib/types";

export function ProfilePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const profile = useQuery({ queryKey: ["profile"], queryFn: api.profile, enabled: open });
  const [form, setForm] = useState<Profile>();
  const [preferences, setPreferences] = useState("");
  const [constraints, setConstraints] = useState("");
  const mutation = useMutation({
    mutationFn: api.updateProfile,
    onSuccess: (value) => {
      queryClient.setQueryData(["profile"], value);
      onClose();
    },
  });

  useEffect(() => {
    if (!profile.data) return;
    setForm(profile.data);
    setPreferences(profile.data.dietary_preferences.join(", "));
    setConstraints(profile.data.constraints.join(", "));
  }, [profile.data]);

  function update<K extends keyof Profile>(key: K, value: Profile[K]) {
    setForm((current) => (current ? { ...current, [key]: value } : current));
  }

  function save() {
    if (!form) return;
    mutation.mutate({
      ...form,
      dietary_preferences: preferences.split(",").map((value) => value.trim()).filter(Boolean),
      constraints: constraints.split(",").map((value) => value.trim()).filter(Boolean),
    });
  }

  return (
    <aside className={`profile-panel ${open ? "profile-panel--open" : ""}`} aria-hidden={!open} aria-label="Health profile">
      <header>
        <div><p className="eyebrow">Explicit memory</p><h2>Your profile</h2></div>
        <button className="icon-button" onClick={onClose} aria-label="Close profile"><Close size={20} /></button>
      </header>
      <p className="profile-panel__intro">Ambrosia uses only confirmed details here. AI suggestions appear as “Remember this” requests and never change the profile silently.</p>
      {form && (
        <div className="profile-form">
          <TextInput id="profile-goal" labelText="Current goal" placeholder="Build fitness, improve sleep…" value={form.goal ?? ""} onChange={(event) => update("goal", event.target.value || null)} />
          <TextInput id="profile-horizon" labelText="Time horizon" placeholder="Next 12 weeks" value={form.time_horizon ?? ""} onChange={(event) => update("time_horizon", event.target.value || null)} />
          <TextInput id="profile-training" labelText="Training frequency" placeholder="Four sessions per week" value={form.training_frequency ?? ""} onChange={(event) => update("training_frequency", event.target.value || null)} />
          <TextArea id="profile-preferences" labelText="Dietary preferences" helperText="Separate items with commas" rows={2} value={preferences} onChange={(event) => setPreferences(event.target.value)} />
          <TextArea id="profile-constraints" labelText="Constraints" helperText="Schedule, injuries, or foods to avoid; do not enter diagnoses or medications" rows={2} value={constraints} onChange={(event) => setConstraints(event.target.value)} />
          <div className="profile-form__row">
            <Select id="distance-unit" labelText="Distance" value={form.distance_unit} onChange={(event) => update("distance_unit", event.target.value as Profile["distance_unit"])}>
              <SelectItem value="miles" text="Miles" />
              <SelectItem value="kilometers" text="Kilometers" />
            </Select>
            <Select id="weight-unit" labelText="Weight" value={form.weight_unit} onChange={(event) => update("weight_unit", event.target.value as Profile["weight_unit"])}>
              <SelectItem value="lb" text="Pounds" />
              <SelectItem value="kg" text="Kilograms" />
            </Select>
          </div>
          {mutation.error && <div className="inline-error" role="alert">{mutation.error.message}</div>}
          <Button onClick={save} disabled={mutation.isPending}>{mutation.isPending ? "Saving…" : "Save confirmed profile"}</Button>
        </div>
      )}
    </aside>
  );
}

