import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'

import claudeIcon from '@/assets/brand/adapter-claude.png'
import geminiIcon from '@/assets/brand/adapter-gemini.png'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useConfig } from '@/app/stores/config-store'
import { cn } from '@/lib/utils'

import { AdapterCard } from './AdapterCard'
import { ApiKeyConnect } from './ApiKeyConnect'
import { EnvCheckRow } from './EnvCheckRow'

/** Adapters that connect with a pasted API key (no CLI / terminal). */
const API_KEY_ADAPTER = 'anthropic-api'

/**
 * Static presentation-only metadata keyed by adapter id. The icon, one-line
 * description and install URL are chrome — every fact the user acts on (name,
 * installed state, version, model list) comes from useConfig() (trust rule).
 */
const ADAPTER_META: Record<string, { icon: string; description: string; installUrl: string }> = {
  'anthropic-api': {
    icon: claudeIcon,
    description: 'Anthropic API — paste a key, no terminal',
    installUrl: 'https://console.anthropic.com/settings/keys',
  },
  'claude-code': {
    icon: claudeIcon,
    description: 'Local Claude agent',
    installUrl: 'https://docs.anthropic.com/en/docs/claude-code/overview',
  },
  'gemini-cli': {
    icon: geminiIcon,
    description: 'Local Gemini agent',
    installUrl: 'https://github.com/google-gemini/gemini-cli',
  },
}

/** "default" reads as "Default"; concrete model ids render as-is. */
function modelLabel(model: string): string {
  return model === 'default' ? 'Default' : model
}

/**
 * F1 — Onboarding step 1 "Choose the model" (Figma 1:12). Connects the local
 * agent CLI that becomes the brain: pick an adapter, pick its model, prove the
 * CLI answers, continue. Renders into the F8 shell's AppLayout content column.
 */
export default function OnboardingModel() {
  const navigate = useNavigate()
  const { config, adapters, loading, saveConfig, runEnvCheck } = useConfig()

  const [showMore, setShowMore] = useState(false)
  // Whether the *currently selected* adapter passed its env-check. Reset on any
  // adapter change so Continue can't inherit a stale pass from another CLI.
  const [envPassed, setEnvPassed] = useState(false)

  const selectedAdapter = config?.adapter ?? null
  const selectedModel = config?.model ?? 'default'

  const selectedAdapterData = useMemo(
    () => adapters.find((adapter) => adapter.id === selectedAdapter),
    [adapters, selectedAdapter],
  )
  const models =
    selectedAdapterData && selectedAdapterData.models.length > 0
      ? selectedAdapterData.models
      : ['default']

  async function selectAdapter(id: string) {
    if (id === selectedAdapter) return
    setEnvPassed(false)
    // Persist the choice and reset model so the picker matches the new adapter.
    await saveConfig({ adapter: id, model: 'default' })
  }

  async function changeModel(model: string) {
    await saveConfig({ model })
  }

  const canContinue = Boolean(selectedAdapter) && envPassed

  if (loading) {
    return (
      <div className="mx-auto flex min-h-[60vh] w-full max-w-[664px] items-center justify-center text-brand-muted">
        Loading…
      </div>
    )
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-9rem)] w-full max-w-[664px] flex-col items-center justify-center gap-14 py-10">
      {/* Heading */}
      <div className="flex w-full max-w-[521px] flex-col items-center gap-4 text-center">
        <h1 className="font-display text-[40px] leading-[1.1] text-foreground">Choose the model</h1>
        <p className="text-[16px] text-brand-muted">
          This will be an engine and brain behind the agent
        </p>
      </div>

      {/* Adapter cards + "more adapters" disclosure */}
      <div className="flex w-full flex-col gap-4">
        <div
          role="radiogroup"
          aria-label="Agent adapter"
          className="grid grid-cols-1 gap-6 sm:grid-cols-2"
        >
          {adapters.map((adapter) => {
            const meta = ADAPTER_META[adapter.id]
            return (
              <AdapterCard
                key={adapter.id}
                adapter={adapter}
                icon={meta?.icon ?? claudeIcon}
                description={meta?.description ?? 'Local agent'}
                selected={selectedAdapter === adapter.id}
                onSelect={() => selectAdapter(adapter.id)}
              />
            )
          })}
        </div>

        <div className="flex flex-col gap-2">
          <Button
            variant="link"
            aria-expanded={showMore}
            onClick={() => setShowMore((value) => !value)}
            className="h-auto gap-1.5 self-start p-0 text-[16px] font-normal leading-[26px]"
          >
            More agent adapter types
            <ChevronDown className={cn('size-4 transition-transform', showMore && 'rotate-180')} />
          </Button>
          {showMore ? (
            <p className="max-w-[560px] text-sm leading-5 text-brand-muted">
              More local adapters are on the way. Additional agent CLIs will plug into YuBen through
              the same interface, so you can swap the brain without changing your workflow.
            </p>
          ) : null}
        </div>
      </div>

      {/* Model select — options derive from the chosen adapter */}
      <div className="flex w-full flex-col gap-3">
        <Label htmlFor="model">Model</Label>
        <Select value={selectedModel} onValueChange={changeModel} disabled={!selectedAdapter}>
          <SelectTrigger id="model">
            <SelectValue placeholder="Default" />
          </SelectTrigger>
          <SelectContent>
            {models.map((model) => (
              <SelectItem key={model} value={model}>
                {modelLabel(model)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Connect step — a key-paste + live ping for the API path, a CLI probe
          otherwise. Both bubble the pass/fail up to gate Continue. */}
      {selectedAdapter === API_KEY_ADAPTER ? (
        <ApiKeyConnect key={API_KEY_ADAPTER} onResult={(result) => setEnvPassed(result.ok)} />
      ) : (
        <EnvCheckRow
          key={selectedAdapter ?? 'none'}
          disabled={!selectedAdapter}
          installUrl={selectedAdapter ? ADAPTER_META[selectedAdapter]?.installUrl : undefined}
          onRun={runEnvCheck}
          onResult={(result) => setEnvPassed(result.ok)}
        />
      )}

      {/* Continue — gated on a selected adapter that passed its connect step */}
      <div className="flex flex-col items-center gap-3">
        <Button
          disabled={!canContinue}
          onClick={() => navigate('/onboarding/setup')}
          className="min-w-[142px]"
        >
          Continue
        </Button>
        {!canContinue ? (
          <p className="text-center text-[13px] text-brand-muted">
            {!selectedAdapter
              ? 'Select an adapter to continue.'
              : selectedAdapter === API_KEY_ADAPTER
                ? 'Add your API key and test it to continue.'
                : 'Run the environment check to continue.'}
          </p>
        ) : null}
      </div>
    </div>
  )
}
