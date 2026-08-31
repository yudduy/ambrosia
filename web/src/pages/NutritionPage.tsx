import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, FileUploaderDropContainer, InlineLoading, TextInput } from "@carbon/react";
import { Checkmark, TrashCan } from "@carbon/icons-react";
import { api } from "../lib/api";
import type { MealAnalysis, NutritionDraft, NutritionRange, RangeName } from "../lib/types";
import { MetricCard } from "../components/MetricCard";
import { RangeSwitch } from "../components/RangeSwitch";
import { TrendChart } from "../components/TrendChart";
import { PageError, PageLoading } from "./HomePage";

export function NutritionPage() {
  const queryClient = useQueryClient();
  const [range, setRange] = useState<RangeName>("28d");
  const [note, setNote] = useState("");
  const [draft, setDraft] = useState<NutritionDraft>();
  const [error, setError] = useState<string>();
  const [selectedFile, setSelectedFile] = useState<File>();
  const query = useQuery({ queryKey: ["nutrition", range], queryFn: () => api.domain("nutrition", range) });
  const upload = useMutation({
    mutationFn: () => api.uploadMeal(selectedFile!, note),
    onSuccess: setDraft,
    onError: (reason) => setError(reason.message),
  });
  const analyze = useMutation({
    mutationFn: () => api.analyzeMeal(draft!.id),
    onSuccess: setDraft,
    onError: (reason) => setError(reason.message),
  });
  const confirm = useMutation({
    mutationFn: () => api.confirmMeal(draft!),
    onSuccess: () => {
      setDraft(undefined);
      setNote("");
      setSelectedFile(undefined);
      void queryClient.invalidateQueries({ queryKey: ["nutrition"] });
      void queryClient.invalidateQueries({ queryKey: ["home"] });
    },
    onError: (reason) => setError(reason.message),
  });

  async function discard() {
    if (draft) await api.discardMeal(draft.id);
    setDraft(undefined);
    setNote("");
    setSelectedFile(undefined);
  }

  if (query.isLoading) return <PageLoading label="nutrition" />;
  if (query.error || !query.data) return <PageError message={query.error?.message} retry={() => query.refetch()} />;
  const { data } = query;
  return (
    <div className="page nutrition-page">
      <section className="page-intro">
        <div><h1>Nutrition</h1>{data.coverage.covered_days > 0 && <p className="page-summary">{data.summary}</p>}</div>
        <RangeSwitch value={range} onChange={setRange} />
      </section>
      <section className="meal-capture">
        <div className="meal-capture__copy">
          <h2>Add meal</h2>
          <p>The photo stays on this Mac until you tap Analyze.</p>
        </div>
        {!draft ? (
          <div className="meal-uploader">
            <FileUploaderDropContainer
              accept={["image/jpeg", "image/png", "image/webp", "image/heic"]}
              labelText="Choose a meal photo"
              multiple={false}
              onAddFiles={(_, { addedFiles }) => { setSelectedFile(addedFiles[0]); setError(undefined); }}
            />
            {selectedFile && <p className="selected-file">{selectedFile.name}</p>}
            <TextInput id="meal-note" labelText="Note (optional)" placeholder="Chicken bowl after the gym" value={note} onChange={(event) => setNote(event.target.value)} />
            <Button disabled={!selectedFile || upload.isPending} onClick={() => upload.mutate()}>{upload.isPending ? "Adding..." : "Add photo"}</Button>
          </div>
        ) : (
          <div className="meal-draft">
            <img src={draft.thumbnail_url} alt="Meal photo" />
            <div className="meal-draft__body">
              {draft.status === "uploaded" || draft.status === "failed" ? (
                <>
                  <h3>Ready to analyze</h3>
                  <p>Analyze sends this photo{draft.note ? ` and the note "${draft.note}"` : ""} to ChatGPT.</p>
                  <div className="meal-actions"><Button onClick={() => analyze.mutate()} disabled={analyze.isPending}>{analyze.isPending ? "Analyzing..." : "Analyze"}</Button><Button kind="ghost" renderIcon={TrashCan} onClick={discard}>Discard</Button></div>
                </>
              ) : draft.status === "analyzing" ? <InlineLoading description="Analyzing photo..." /> : draft.analysis ? (
                <MealEditor analysis={draft.analysis} onChange={(analysis) => setDraft({ ...draft, analysis })} />
              ) : null}
            </div>
            {draft.status === "ready" && (
              <div className="meal-confirm-bar"><Button kind="ghost" renderIcon={TrashCan} onClick={discard}>Discard</Button><Button renderIcon={Checkmark} onClick={() => confirm.mutate()} disabled={confirm.isPending}>{confirm.isPending ? "Saving..." : "Save meal"}</Button></div>
            )}
          </div>
        )}
        {error && <div className="inline-error" role="alert">{error}</div>}
      </section>
      <section className="nutrition-data-grid">
        <div className="trend-section"><div className="trend-section__header"><h2>{data.metrics[0]?.label ?? "Calories"}</h2></div><TrendChart metric={data.metrics[0]} /></div>
        <div className="metric-grid metric-grid--nutrition">{data.metrics.map((metric) => <MetricCard key={metric.key} metric={metric} compact />)}</div>
      </section>
    </div>
  );
}

function MealEditor({ analysis, onChange }: { analysis: MealAnalysis; onChange: (value: MealAnalysis) => void }) {
  function updateRange(key: "calories" | "protein_g" | "carbs_g" | "fat_g" | "sodium_mg", side: keyof NutritionRange, value: number) {
    const current = analysis[key] ?? { low: 0, high: 0 };
    onChange({ ...analysis, [key]: { ...current, [side]: Math.max(0, value) } });
  }
  return (
    <div className="meal-editor">
      <TextInput id="meal-description" labelText="Meal description" value={analysis.description} onChange={(event) => onChange({ ...analysis, description: event.target.value })} />
      <div className="range-table">
        {([
          ["calories", "Calories", "kcal"], ["protein_g", "Protein", "g"], ["carbs_g", "Carbohydrate", "g"], ["fat_g", "Fat", "g"], ["sodium_mg", "Sodium", "mg"],
        ] as const).map(([key, label, unit]) => {
          const value = analysis[key] ?? { low: 0, high: 0 };
          return <div className="range-row" key={key}><span>{label}<small>{unit}</small></span><label>Low<input type="number" min="0" value={value.low} onChange={(event) => updateRange(key, "low", Number(event.target.value))} /></label><span className="range-dash">to</span><label>High<input type="number" min="0" value={value.high} onChange={(event) => updateRange(key, "high", Number(event.target.value))} /></label></div>;
        })}
      </div>
      <div className="ingredient-editor"><span>Ingredients</span><input value={analysis.ingredients.join(", ")} onChange={(event) => onChange({ ...analysis, ingredients: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></div>
      <p className="uncertainty-note"><strong>{Math.round(analysis.confidence * 100)}% confidence.</strong> {analysis.uncertainty_note}</p>
    </div>
  );
}
