import { useEffect, useMemo, useState } from 'react'
import type { ComponentType, SVGProps } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'

import {
  ClaudeMark,
  CopilotMark,
  CursorMark,
  GeminiMark,
  OllamaMark,
  OpenAIMark,
  OpenCodeMark,
  OpenRouterMark,
  QwenMark,
  TerminalMark,
} from '@/app/adapter-icons'
import type { Adapter, KeyProvider } from '@/lib/types'
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

/**
 * The adapters shown up front, in grid order — paired by vendor so each row is
 * "the API key" next to "the CLI" for the same brand: Anthropic, then OpenAI,
 * then Gemini alongside Cursor. Everything else is a real option too, just one
 * click away under the disclosure, so the first screen stays a short choice
 * between familiar names instead of a wall of twelve cards.
 *
 * Presentation order lives here rather than in the backend registry: the API
 * reports adapters in its own logical order (key-paste providers first), and how
 * that gets arranged is the screen's business.
 */
const FEATURED_ADAPTERS = [
  'anthropic-api',
  'claude-code',
  'openai-api',
  'codex-cli',
  'gemini-cli',
  'cursor-cli',
]

const FEATURED_SET = new Set(FEATURED_ADAPTERS)

/**
 * Static presentation-only metadata keyed by adapter id. The icon, one-line
 * description and install URL are chrome — every fact the user acts on (name,
 * installed state, version, model list) comes from useConfig() (trust rule).
 *
 * `key` marks the adapters that connect by pasting a credential instead of
 * probing a local CLI; its fields drive <ApiKeyConnect/>. `experimental` marks
 * the agent CLIs whose headless invocation is transcribed from their docs but
 * hasn't been run end-to-end (see backend cli_agents.CLI_SPECS.verified).
 */
interface AdapterMeta {
  Icon: ComponentType<SVGProps<SVGSVGElement>>
  description: string
  installUrl: string
  experimental?: boolean
  key?: {
    provider: KeyProvider
    label: string
    placeholder: string
    consoleUrl: string
    consoleName: string
  }
}

const ADAPTER_META: Record<string, AdapterMeta> = {
  'anthropic-api': {
    Icon: ClaudeMark,
    description: 'Claude — paste a key, no terminal',
    installUrl: 'https://console.anthropic.com/settings/keys',
    key: {
      provider: 'anthropic',
      label: 'Anthropic API key',
      placeholder: 'sk-ant-…',
      consoleUrl: 'https://console.anthropic.com/settings/keys',
      consoleName: 'the Anthropic Console',
    },
  },
  'openai-api': {
    Icon: OpenAIMark,
    description: 'GPT — paste a key, no terminal',
    installUrl: 'https://platform.openai.com/api-keys',
    key: {
      provider: 'openai',
      label: 'OpenAI API key',
      placeholder: 'sk-…',
      consoleUrl: 'https://platform.openai.com/api-keys',
      consoleName: 'the OpenAI platform',
    },
  },
  openrouter: {
    Icon: OpenRouterMark,
    description: 'One key, hundreds of models',
    installUrl: 'https://openrouter.ai/keys',
    key: {
      provider: 'openrouter',
      label: 'OpenRouter API key',
      placeholder: 'sk-or-…',
      consoleUrl: 'https://openrouter.ai/keys',
      consoleName: 'OpenRouter',
    },
  },
  ollama: {
    Icon: OllamaMark,
    description: 'Local models — free, no key',
    installUrl: 'https://ollama.com/download',
  },
  'claude-code': {
    Icon: ClaudeMark,
    description: 'Local Claude agent',
    installUrl: 'https://docs.anthropic.com/en/docs/claude-code/overview',
  },
  'gemini-cli': {
    Icon: GeminiMark,
    description: 'Local Gemini agent',
    installUrl: 'https://github.com/google-gemini/gemini-cli',
  },
  'codex-cli': {
    Icon: OpenAIMark,
    description: 'OpenAI’s local agent',
    installUrl: 'https://developers.openai.com/codex',
  },
  'cursor-cli': {
    Icon: CursorMark,
    description: 'Cursor’s headless agent',
    installUrl: 'https://cursor.com/docs/cli/headless',
  },
  'opencode-cli': {
    Icon: OpenCodeMark,
    description: 'Open-source local agent',
    installUrl: 'https://opencode.ai/docs/cli/',
  },
  'qwen-cli': {
    Icon: QwenMark,
    description: 'Alibaba’s local agent',
    installUrl: 'https://github.com/QwenLM/qwen-code',
    experimental: true,
  },
  'copilot-cli': {
    Icon: CopilotMark,
    description: 'GitHub’s local agent',
    installUrl: 'https://docs.github.com/copilot/concepts/agents/about-copilot-cli',
    experimental: true,
  },
  'amp-cli': {
    Icon: TerminalMark,
    description: 'Sourcegraph’s local agent',
    installUrl: 'https://ampcode.com/manual',
    experimental: true,
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

  // Split into the featured grid (fixed order) and the collapsed remainder
  // (registry order). Unknown ids fall through to the remainder rather than
  // vanishing, so a newly registered backend adapter is always reachable.
  const { featured, more } = useMemo(() => {
    const byId = new Map(adapters.map((adapter) => [adapter.id, adapter]))
    return {
      featured: FEATURED_ADAPTERS.map((id) => byId.get(id)).filter(
        (adapter): adapter is Adapter => Boolean(adapter),
      ),
      more: adapters.filter((adapter) => !FEATURED_SET.has(adapter.id)),
    }
  }, [adapters])

  // A selection restored from config may live in the collapsed group; reveal it
  // once, or the screen reads as "nothing selected" while Continue is enabled.
  useEffect(() => {
    if (selectedAdapter && !FEATURED_SET.has(selectedAdapter)) setShowMore(true)
  }, [selectedAdapter])
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

  // Present only for adapters that connect by pasting a credential.
  const keyConfig = selectedAdapter ? ADAPTER_META[selectedAdapter]?.key : undefined

  const canContinue = Boolean(selectedAdapter) && envPassed

  /** One card, wherever it renders — featured grid or collapsed remainder. */
  function renderCard(adapter: Adapter) {
    const meta = ADAPTER_META[adapter.id]
    return (
      <AdapterCard
        key={adapter.id}
        adapter={adapter}
        Icon={meta?.Icon ?? TerminalMark}
        description={meta?.description ?? 'Local agent'}
        experimental={meta?.experimental}
        selected={selectedAdapter === adapter.id}
        onSelect={() => selectAdapter(adapter.id)}
      />
    )
  }

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

      {/* Featured grid + "more adapters" disclosure. One radiogroup spans both
          so the collapsed cards stay part of the same single-choice control. */}
      <div className="flex w-full flex-col gap-4" role="radiogroup" aria-label="Agent adapter">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">{featured.map(renderCard)}</div>

        {more.length > 0 ? (
          <div className="flex flex-col gap-4">
            <Button
              variant="link"
              aria-expanded={showMore}
              onClick={() => setShowMore((value) => !value)}
              className="h-auto gap-1.5 self-start p-0 text-[16px] font-normal leading-[26px]"
            >
              {showMore ? 'Fewer adapters' : `More adapters (${more.length})`}
              <ChevronDown className={cn('size-4 transition-transform', showMore && 'rotate-180')} />
            </Button>
            {showMore ? (
              <>
                <p className="max-w-[560px] text-sm leading-5 text-brand-muted">
                  Every adapter below works the same way — pick one and YuBen swaps the brain
                  without changing your workflow. OpenRouter reaches hundreds of models with a
                  single key; Ollama runs models on your own machine, free and without one.
                </p>
                <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">{more.map(renderCard)}</div>
              </>
            ) : null}
          </div>
        ) : null}
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

      {/* Connect step — a key-paste + live ping for the API paths, a CLI probe
          otherwise. Both bubble the pass/fail up to gate Continue. */}
      {keyConfig && selectedAdapter ? (
        <ApiKeyConnect
          key={selectedAdapter}
          adapterId={selectedAdapter}
          provider={keyConfig.provider}
          label={keyConfig.label}
          placeholder={keyConfig.placeholder}
          consoleUrl={keyConfig.consoleUrl}
          consoleName={keyConfig.consoleName}
          onResult={(result) => setEnvPassed(result.ok)}
        />
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
              : keyConfig
                ? 'Add your API key and test it to continue.'
                : 'Run the environment check to continue.'}
          </p>
        ) : null}
      </div>
    </div>
  )
}
