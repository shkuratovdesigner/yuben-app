import { LayoutGrid, List } from 'lucide-react'

import logoMark from '@/assets/brand/logo-mark.svg'
import { ClaudeMark, GeminiMark } from '@/app/adapter-icons'
import { Button } from '@/components/ui/button'
import { Badge, vsrTier } from '@/components/ui/badge'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { KeyInput } from '@/components/ui/key-input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableScroll,
} from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'

const SWATCHES: [string, string][] = [
  ['ink #2B2D33', 'bg-foreground'],
  ['grey #777274', 'bg-brand-grey'],
  ['border #D5D5D6', 'bg-border'],
  ['teal #04607D', 'bg-brand-teal'],
  ['link #00809C', 'bg-brand-link'],
  ['selected #19B28D', 'bg-brand-selected'],
  ['hot ≥5×', 'bg-tier-hot'],
  ['warm 2–5×', 'bg-tier-warm'],
  ['cool <1×', 'bg-tier-cool'],
]

const SAMPLE_ROWS = [
  { n: 1, title: 'The Money-Making Secrets Behind Hotel Design', channel: 'WSJ', views: 2819786, vsr: 0.43, eng: 14.7, dur: '6:39' },
  { n: 2, title: 'Лучшие идеи звучат как бред. Уроки Airbnb', channel: 'Денис Викторов', views: 1048791, vsr: 41.62, eng: 20.7, dur: '3:00' },
  { n: 3, title: 'The REAL Reason the Airbnb Market Collapsed', channel: 'Zac Rios', views: 700433, vsr: 10.09, eng: 16.2, dur: '19:23' },
  { n: 4, title: 'Why the Airbnb Market Has COLLAPSED in 2026', channel: 'Zac Rios', views: 864401, vsr: 2.02, eng: 21.5, dur: '23:43' },
]

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4 border-t border-border pt-8">
      <h2 className="text-xs font-medium uppercase tracking-widest text-brand-grey">{title}</h2>
      {children}
    </section>
  )
}

/**
 * W0.3 design-system preview. Renders every shared primitive so the Figma
 * tokens can be verified visually. F8 (App shell) replaces App.tsx with the
 * router in Phase 1; this screen can stay reachable for reference.
 */
export default function DesignPreview() {
  return (
    <div className="mx-auto flex max-w-[900px] flex-col gap-10 px-6 py-14">
      <header className="flex items-center gap-2">
        <img src={logoMark} alt="" className="size-7" />
        <span className="text-[16px] font-medium tracking-tight">YuBen</span>
        <Badge variant="outline" className="ml-2">
          design system
        </Badge>
      </header>

      <Section title="Typography">
        <p className="font-display text-[40px] leading-[1.1] text-foreground">Choose the model</p>
        <p className="text-base text-brand-muted">
          This will be an engine and brain behind the agent — Inter body at 16px.
        </p>
        <p className="text-label-lg font-medium">Label Large · 14 / 20 / 0.1 tracking</p>
      </Section>

      <Section title="Color tokens">
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">
          {SWATCHES.map(([label, bg]) => (
            <div key={label} className="flex flex-col gap-1.5">
              <div className={`h-12 rounded-lg border border-border ${bg}`} />
              <span className="text-[11px] text-brand-grey">{label}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Buttons (pill)">
        <div className="flex flex-wrap items-center gap-3">
          <Button>Continue</Button>
          <Button variant="secondary" size="sm">
            Test now
          </Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="link">More agent adapter types</Button>
          <Button disabled>Disabled</Button>
        </div>
      </Section>

      <Section title="Cards — adapter select (active vs resting)">
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
          <Card active className="p-6">
            <ClaudeMark className="mb-5 size-14" />
            <CardTitle>Claude Code</CardTitle>
            <CardDescription>Local Claude agent</CardDescription>
          </Card>
          <Card className="p-6">
            <GeminiMark className="mb-5 size-14" />
            <CardTitle className="text-[#55575c]">Gemini CLI</CardTitle>
            <CardDescription>Local Gemini agent</CardDescription>
          </Card>
        </div>
      </Section>

      <Section title="Form controls">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="model">Model</Label>
            <Select defaultValue="default">
              <SelectTrigger id="model">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">Default</SelectItem>
                <SelectItem value="claude-opus-4-8">claude-opus-4-8</SelectItem>
                <SelectItem value="claude-sonnet-5">claude-sonnet-5</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="q">Topic</Label>
            <Input id="q" placeholder="What content are you searching for?" />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="key">Private YouTube Key</Label>
            <KeyInput id="key" placeholder="AIza…" defaultValue="AIzaSyDEMOkey_local_only_1234" />
          </div>
          <div className="flex items-center gap-6">
            <label className="flex items-center gap-2 text-sm">
              <Checkbox defaultChecked /> Titles Analytic
            </label>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox /> Script analytics
            </label>
          </div>
        </div>
      </Section>

      <Section title="Progress">
        <div className="flex flex-col gap-3">
          <Progress value={64} />
          <Progress indeterminate />
        </div>
      </Section>

      <Section title="Toggle + badges">
        <div className="flex flex-wrap items-center gap-4">
          <ToggleGroup type="single" defaultValue="grid">
            <ToggleGroupItem value="grid">
              <LayoutGrid className="size-4" /> Grid
            </ToggleGroupItem>
            <ToggleGroupItem value="list">
              <List className="size-4" /> List
            </ToggleGroupItem>
          </ToggleGroup>
          <Badge variant="hot">41.6× hot</Badge>
          <Badge variant="warm">2.0× warm</Badge>
          <Badge variant="cool">0.4× cool</Badge>
          <Badge variant="count">Research history 3</Badge>
          <Badge variant="promoted">promoted</Badge>
        </div>
      </Section>

      <Section title="Tabs + table (VSR tiers)">
        <Tabs defaultValue="titles">
          <TabsList>
            <TabsTrigger value="titles">Title Analysis</TabsTrigger>
            <TabsTrigger value="script">Script Analysis</TabsTrigger>
          </TabsList>
          <TabsContent value="titles">
            <TableScroll className="rounded-[12px] border border-border">
              <Table>
                <TableHeader sticky>
                  <TableRow>
                    <TableHead>№</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead>Channel</TableHead>
                    <TableHead className="text-right">Views</TableHead>
                    <TableHead className="text-right">Mult</TableHead>
                    <TableHead className="text-right">Eng/1k</TableHead>
                    <TableHead className="text-right">Dur</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {SAMPLE_ROWS.map((r) => (
                    <TableRow key={r.n}>
                      <TableCell className="text-brand-grey">{r.n}</TableCell>
                      <TableCell className="max-w-[280px] truncate font-medium">{r.title}</TableCell>
                      <TableCell className="text-brand-grey">{r.channel}</TableCell>
                      <TableCell className="text-right tabular-nums">{r.views.toLocaleString()}</TableCell>
                      <TableCell className="text-right">
                        <Badge variant={vsrTier(r.vsr)}>{r.vsr}×</Badge>
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-brand-grey">{r.eng}</TableCell>
                      <TableCell className="text-right tabular-nums text-brand-grey">{r.dur}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableScroll>
          </TabsContent>
          <TabsContent value="script">
            <p className="text-sm text-brand-muted">Script analysis content…</p>
          </TabsContent>
        </Tabs>
      </Section>
    </div>
  )
}
