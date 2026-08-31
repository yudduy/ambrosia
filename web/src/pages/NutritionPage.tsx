import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, FileUploaderDropContainer, InlineLoading, TextInput } from "@carbon/react";
import { Camera, Checkmark, TrashCan } from "@carbon/icons-react";
import { api } from "../lib/api";
import type { MealAnalysis, NutritionDraft, NutritionRange, RangeName } from "../lib/types";
import { CoverageBanner } from "../components/CoverageBanner";
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

  if (query.isLoading) return <PageLoading label="Building your nutrition view" />;
  if (query.error || !query.data) return <PageError message={query.error?.message} retry={() => query.refetch()} />;
  const { data } = query;
  return (
    <div className="page nutrition-page">
      <section className="page-intro">
        <div><p className="eyebrow">Meals and hydration</p><h1>Nutrition</h1><p>Confirmed ranges—not false precision—from imports and meals you approve.</p></div>
        <RangeSwitch value={range} onChange={setRange} />
      </section>
      <CoverageBanner coverage={data.coverage} provenance={data.provenance} />
      <section className="meal-capture">
        <div className="meal-capture__copy">
          <span className="meal-capture__icon"><Camera size={22} /></span>
          <p className="eyebrow">Add a meal</p>
          <h2>Photograph it. Review the range. Confirm it.</h2>
          <p>Ambrosia strips location metadata and resizes the image here on the Mac. It is sent to OpenAI only when you choose Analyze.</p>
        </div>
        {!draft ? (
          <div className="meal-uploader">
            <FileUploaderDropContainer
              accept={["image/jpeg", "image/png", "image/webp", "image/heic"]}
              labelText="Drop a meal photo or choose one"
              multiple={false}
              onAddFiles={(_, { addedFiles }) => { setSelectedFile(addedFiles[0]); setError(undefined); }}
            />
            {selectedFile && <p className="selected-file">Selected: {selectedFile.name}</p>}
            <TextInput id="meal-note" labelText="Optional context" placeholder="Chicken bowl after the gym" value={note} onChange={(event) => setNote(event.target.value)} />
            <Button disabled={!selectedFile || upload.isPending} onClick={() => upload.mutate()}>{upload.isPending ? "Sanitizing photo…" : "Create private draft"}</Button>
          </div>
        ) : (
          <div className="meal-draft">
            <img src={draft.thumbnail_url} alt="Sanitized meal draft" />
            <div className="meal-draft__body">
              <div className="meal-draft__status"><span className={`status-dot status-dot--${draft.status}`} />{draft.status}</div>
              {draft.status === "uploaded" || draft.status === "failed" ? (
                <>
                  <h3>Photo is local and sanitized.</h3>
                  <p>Analyze sends this image and “{draft.note || "no note"}” to your ChatGPT account.</p>
                  <div className="meal-actions"><Button onClick={() => analyze.mutate()} disabled={analyze.isPending}>{analyze.isPending ? "Analyzing…" : "Analyze with AI"}</Button><Button kind="ghost" renderIcon={TrashCan} onClick={discard}>Discard</Button></div>
                </>
              ) : draft.status === "analyzing" ? <InlineLoading description="Estimating conservative nutrition ranges" /> : draft.analysis ? (
                <MealEditor analysis={draft.analysis} onChange={(analysis) => setDraft({ ...draft, analysis })} />
              ) : null}
            </div>
            {draft.status === "ready" && (
              <div className="meal-confirm-bar"><span><strong>Nothing is saved yet.</strong><small>Review every range before confirming.</small></span><Button kind="ghost" renderIcon={TrashCan} onClick={discard}>Discard</Button><Button renderIcon={Checkmark} onClick={() => confirm.mutate()} disabled={confirm.isPending}>{confirm.isPending ? "Saving…" : "Confirm meal"}</Button></div>
            )}
          </div>
        )}
        {error && <div className="inline-error" role="alert">{error}</div>}
      </section>
      <section className="insight-band"><span>Current read</span><h2>{data.summary}</h2></section>
      <section className="nutrition-data-grid">
        <div className="trend-section"><div className="trend-section__header"><div><p className="eyebrow">Confirmed history</p><h2>{data.metrics[0]?.label ?? "Logged nutrition"}</h2></div></div><TrendChart metric={data.metrics[0]} /></div>
        <div className="metric-grid metric-grid--nutrition">{data.metrics.map((metric) => <MetricCard key={metric.key} metric={metric} compact />)}</div>
      </section>
      <section className="exploratory-note"><p className="eyebrow">About “debloating”</p><h2>Explore inputs, not facial scores.</h2><p>Ask Ambrosia about sodium, hydration, carbohydrate timing, sleep, or perceived bloating. The app does not claim to measure facial structure or diagnose the cause.</p></section>
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
          return <div className="range-row" key={key}><span>{label}<small>{unit}</small></span><label>Low<input type="number" min="0" value={value.low} onChange={(event) => updateRange(key, "low", Number(event.target.value))} /></label><span className="range-dash">—</span><label>High<input type="number" min="0" value={value.high} onChange={(event) => updateRange(key, "high", Number(event.target.value))} /></label></div>;
        })}
      </div>
      <div className="ingredient-editor"><span>Visible ingredients</span><input value={analysis.ingredients.join(", ")} onChange={(event) => onChange({ ...analysis, ingredients: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></div>
      <p className="uncertainty-note"><strong>{Math.round(analysis.confidence * 100)}% image confidence.</strong> {analysis.uncertainty_note}</p>
    </div>
  );
}
