import React, { ChangeEvent } from 'react';

interface ApiProviderSelectorProps {
    apiProvider?: string;
    onApiProviderChange: (event: ChangeEvent<HTMLSelectElement>) => void;
}

export default function ApiProviderSelector({ apiProvider, onApiProviderChange }: ApiProviderSelectorProps) {
    return (
        <div className="form-group">
            <label htmlFor="apiProvider" className="agent_question">API Provider </label>
            <select
                name="apiProvider"
                id="apiProvider"
                value={apiProvider || 'official'}
                onChange={onApiProviderChange}
                className="form-control-static"
                required
            >
                <option value="official">Official OpenAI (Use your OpenAI Keys)</option>
                <option value="bltcy">BLTCY (Managed Service - gpt-5.2-pro)</option>
            </select>
        </div>
    );
} 
