import React from "react";
import { AdvancedSettings } from "@/types/data";
import { DEFAULT_ADVANCED_SETTINGS } from "@/constants/researchSettings";

interface AdvancedResearchSettingsProps {
  reportType: string;
  settings?: AdvancedSettings;
  onChange: (next: AdvancedSettings) => void;
}

const SETTINGS_BOUNDS = {
  deep_research_breadth: { min: 1, max: 12 },
  deep_research_depth: { min: 1, max: 6 },
  deep_research_concurrency: { min: 1, max: 12 },
  max_search_results_per_query: { min: 1, max: 20 },
  max_iterations: { min: 1, max: 10 },
} as const;

type NumericSettingName = keyof AdvancedSettings;

function clampToRange(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export default function AdvancedResearchSettings({
  reportType,
  settings,
  onChange,
}: AdvancedResearchSettingsProps) {
  const currentSettings = {
    ...DEFAULT_ADVANCED_SETTINGS,
    ...(settings || {}),
  };

  const updateSetting = (name: NumericSettingName, rawValue: string) => {
    if (rawValue === "") {
      return;
    }

    const parsed = Number.parseInt(rawValue, 10);
    if (Number.isNaN(parsed)) {
      return;
    }

    const { min, max } = SETTINGS_BOUNDS[name];
    const clamped = clampToRange(parsed, min, max);

    onChange({
      ...currentSettings,
      [name]: clamped,
    });
  };

  const numericInputClassName = "form-control-static";

  return (
    <div className="form-group">
      <label className="agent_question">Advanced Settings</label>
      <p className="text-muted">
        Deep settings apply to the &quot;Deep Research Report&quot; type.
      </p>

      {reportType === "deep" ? (
        <>
          <div className="form-group">
            <label htmlFor="deep_research_breadth" className="agent_question">Deep Breadth (1-12)</label>
            <input
              id="deep_research_breadth"
              type="number"
              min={SETTINGS_BOUNDS.deep_research_breadth.min}
              max={SETTINGS_BOUNDS.deep_research_breadth.max}
              step={1}
              value={currentSettings.deep_research_breadth}
              onChange={(e) => updateSetting("deep_research_breadth", e.target.value)}
              className={numericInputClassName}
            />
          </div>

          <div className="form-group">
            <label htmlFor="deep_research_depth" className="agent_question">Deep Depth (1-6)</label>
            <input
              id="deep_research_depth"
              type="number"
              min={SETTINGS_BOUNDS.deep_research_depth.min}
              max={SETTINGS_BOUNDS.deep_research_depth.max}
              step={1}
              value={currentSettings.deep_research_depth}
              onChange={(e) => updateSetting("deep_research_depth", e.target.value)}
              className={numericInputClassName}
            />
          </div>

          <div className="form-group">
            <label htmlFor="deep_research_concurrency" className="agent_question">Deep Concurrency (1-12)</label>
            <input
              id="deep_research_concurrency"
              type="number"
              min={SETTINGS_BOUNDS.deep_research_concurrency.min}
              max={SETTINGS_BOUNDS.deep_research_concurrency.max}
              step={1}
              value={currentSettings.deep_research_concurrency}
              onChange={(e) => updateSetting("deep_research_concurrency", e.target.value)}
              className={numericInputClassName}
            />
          </div>
        </>
      ) : null}

      <div className="form-group">
        <label htmlFor="max_search_results_per_query" className="agent_question">Max Search Results / Query (1-20)</label>
        <input
          id="max_search_results_per_query"
          type="number"
          min={SETTINGS_BOUNDS.max_search_results_per_query.min}
          max={SETTINGS_BOUNDS.max_search_results_per_query.max}
          step={1}
          value={currentSettings.max_search_results_per_query}
          onChange={(e) => updateSetting("max_search_results_per_query", e.target.value)}
          className={numericInputClassName}
        />
      </div>

      <div className="form-group">
        <label htmlFor="max_iterations" className="agent_question">Max Research Iterations (1-10)</label>
        <input
          id="max_iterations"
          type="number"
          min={SETTINGS_BOUNDS.max_iterations.min}
          max={SETTINGS_BOUNDS.max_iterations.max}
          step={1}
          value={currentSettings.max_iterations}
          onChange={(e) => updateSetting("max_iterations", e.target.value)}
          className={numericInputClassName}
        />
      </div>
    </div>
  );
}
