import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, FileUploaderButton, InlineLoading, TextInput } from "@carbon/react";
import { Checkmark, Image, Send, TrashCan } from "@carbon/icons-react";
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
  const [previewUrl, setPreviewUrl] = useState<string>();
  const query = useQuery({ queryKey: ["nutrition", range], queryFn: () => api.domain("nutrition", range) });
  const submit = useMutation({
    mutationFn: async () => {
      const uploaded = await api.uploadMeal(selectedFile!, note);
      setDraft(uploaded);
      setPreviewUrl(undefined);
      return api.analyzeMeal(uploaded.id);
    },
    onSuccess: setDraft,
    onError: (reason) => setError(reason.message),
  });
  const retry = useMutation({
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
      setPreviewUrl(undefined);
      void queryClient.invalidateQueries({ queryKey: ["nutrition"] });
      void queryClient.invalidateQueries({ queryKey: ["home"] });
    },
    onError: (reason) => setError(reason.message),
  });

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  function choosePhoto(file?: File) {
    if (!file) return;
    setSelectedFile(file);
    setPreviewUrl(URL.createObjectURL(file));
    setError(undefined);
  }

  async function discard() {
    if (draft) await api.discardMeal(draft.id);
    setDraft(undefined);
    setNote("");
    setSelectedFile(undefined);
    setPreviewUrl(undefined);
    setError(undefined);
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
      <section className="meal-analyzer" aria-labelledby="meal-analyzer-title">
        <div className="meal-thread" aria-live="polite">
          {!draft ? (
            <div className="meal-thread__empty">
              <Image size={22} aria-hidden="true" />
              <h2 id="meal-analyzer-title">Analyze a meal</h2>
              <p>Add a photo. Ambrosia will estimate calories and macros.</p>
            </div>
          ) : (
            <>
              <article className="meal-turn meal-turn--photo">
                <img src={draft.thumbnail_url} alt="Meal submitted for analysis" />
                {draft.note && <p>{draft.note}</p>}
              </article>
              {(submit.isPending || retry.isPending || draft.status === "analyzing") ? (
                <article className="meal-turn meal-turn--reply"><InlineLoading description="Analyzing meal..." /></article>
              ) : draft.analysis ? (
                <article className="meal-turn meal-turn--reply">
                  <h3>Estimate</h3>
                  <MealEditor analysis={draft.analysis} onChange={(analysis) => setDraft({ ...draft, analysis })} />
                  <div className="meal-reply-actions">
                    <Button kind="ghost" renderIcon={TrashCan} onClick={discard}>Discard</Button>
                    <Button renderIcon={Checkmark} onClick={() => confirm.mutate()} disabled={confirm.isPending}>{confirm.isPending ? "Saving..." : "Save meal"}</Button>
                  </div>
                </article>
              ) : (
                <article className="meal-turn meal-turn--reply">
                  <h3>Analysis stopped</h3>
                  <p>Try again or discard this photo.</p>
                  <div className="meal-reply-actions">
                    <Button kind="ghost" renderIcon={TrashCan} onClick={discard}>Discard</Button>
                    <Button onClick={() => retry.mutate()} disabled={retry.isPending}>Try again</Button>
                  </div>
                </article>
              )}
            </>
          )}
        </div>
        {!draft && (
          <div className="meal-composer">
            {selectedFile && previewUrl && (
              <div className="meal-composer__preview">
                <img src={previewUrl} alt="Selected meal" />
                <div><strong>{selectedFile.name}</strong><span>Ready to analyze</span></div>
                <Button hasIconOnly kind="ghost" size="sm" iconDescription="Remove photo" renderIcon={TrashCan} onClick={() => { setSelectedFile(undefined); setPreviewUrl(undefined); }} />
              </div>
            )}
            <TextInput id="meal-note" labelText="Meal note" placeholder="Chicken bowl after the gym" value={note} onChange={(event) => setNote(event.target.value)} />
            <div className="meal-composer__actions">
              <FileUploaderButton
                accept={["image/jpeg", "image/png", "image/webp", "image/heic"]}
                buttonKind="ghost"
                disableLabelChanges
                labelText={<><Image size={16} aria-hidden="true" />Photo</>}
                multiple={false}
                onChange={(event) => choosePhoto(event.target.files?.[0])}
              />
              <Button renderIcon={Send} disabled={!selectedFile || submit.isPending} onClick={() => submit.mutate()}>{submit.isPending ? "Analyzing..." : "Analyze meal"}</Button>
            </div>
            <p className="meal-composer__disclosure">Your photo and note are sent to OpenAI for analysis.</p>
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
