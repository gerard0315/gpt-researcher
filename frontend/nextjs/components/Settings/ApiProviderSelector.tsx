import React, { ChangeEvent } from 'react';
import { ModelConfig, ModelPreset } from '@/types/data';

const MODEL_OPTIONS: { value: ModelPreset; label: string }[] = [
  { value: 'official_gpt52pro', label: 'Official OpenAI - gpt-5.2-pro' },
  { value: 'bltcy_gpt52pro', label: 'BLTCY - gpt-5.2-pro' },
  { value: 'official_gpt4o', label: 'Official OpenAI - gpt-4o' },
  { value: 'kimi_k2_turbo', label: 'Kimi - k2-turbo-preview' },
];

const DEFAULT_MODEL_CONFIG: ModelConfig = {
  fast: 'official_gpt4o',
  smart: 'kimi_k2_turbo',
  strategic: 'bltcy_gpt52pro',
};

interface ApiProviderSelectorProps {
  modelConfig?: ModelConfig;
  onModelConfigChange: (config: ModelConfig) => void;
}

export default function ApiProviderSelector({ modelConfig, onModelConfigChange }: ApiProviderSelectorProps) {
  const config = modelConfig || DEFAULT_MODEL_CONFIG;

  const handleChange = (tier: keyof ModelConfig) => (e: ChangeEvent<HTMLSelectElement>) => {
    onModelConfigChange({
      ...config,
      [tier]: e.target.value as ModelPreset,
    });
  };

  return (
    <div className="form-group" style={{ flexDirection: 'column', alignItems: 'stretch', gap: '8px' }}>
      <label className="agent_question">Model Configuration</label>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ minWidth: '80px', fontSize: '0.85rem', color: 'rgba(255,255,255,0.7)' }}>Fast</span>
        <select
          value={config.fast}
          onChange={handleChange('fast')}
          className="form-control-static"
          style={{ flex: 1 }}
        >
          {MODEL_OPTIONS.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ minWidth: '80px', fontSize: '0.85rem', color: 'rgba(255,255,255,0.7)' }}>Smart</span>
        <select
          value={config.smart}
          onChange={handleChange('smart')}
          className="form-control-static"
          style={{ flex: 1 }}
        >
          {MODEL_OPTIONS.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ minWidth: '80px', fontSize: '0.85rem', color: 'rgba(255,255,255,0.7)' }}>Strategic</span>
        <select
          value={config.strategic}
          onChange={handleChange('strategic')}
          className="form-control-static"
          style={{ flex: 1 }}
        >
          {MODEL_OPTIONS.map(opt => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>
    </div>
  );
}
