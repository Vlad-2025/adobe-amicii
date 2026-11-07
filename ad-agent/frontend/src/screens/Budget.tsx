import { useState } from "react";
import { Button, ButtonGroup, Flex, Heading, ProgressCircle, Text } from "@adobe/react-spectrum";
import { HYPO_LABEL, eur, post, queryClient, useApi } from "../api";
import { Card, Kpi } from "../components/ui";

export default function Budget() {
  const q = useApi<any[]>("budget", "/api/budget/actions");
  const ev = useApi("eval", "/api/eval");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const propose = async () => {
    setBusy(true);
    const r = await post("/api/budget/propose");
    setNote(r.created.length ? `${r.created.length} new proposal(s)${r.created.some((c: any) => c.discord_sent) ? " · sent to Discord" : ""}` : `No new proposals (${r.considered} considered; the counterfactual must show money saved)`);
    setBusy(false);
    queryClient.invalidateQueries();
  };
  const decide = async (id: number, decision: string) => {
    await post(`/api/budget/actions/${id}/approve?decision=${decision}`);
    queryClient.invalidateQueries();
  };
  if (!q.data) return <ProgressCircle isIndeterminate aria-label="loading" />;
  const proposed = q.data.filter((a) => a.status === "proposed");
  const decided = q.data.filter((a) => a.status !== "proposed");
  return (
    <Flex direction="column" gap="size-250">
      <Flex alignItems="center" gap="size-200" wrap>
        <Heading level={2} margin={0}>Budget Autopilot</Heading>
        <Text UNSAFE_style={{ opacity: 0.7 }}>Proposals stay inside each campaign's max CPA, min ROAS and total budget. Nothing changes without approval.</Text>
        <div style={{ flex: 1 }} />
        <Button variant="cta" onPress={propose} isPending={busy}>Find budget actions</Button>
      </Flex>
      {note && <Text>{note}</Text>}
      <Flex gap="size-200" wrap>
        <Kpi label="€ protected by approved actions (counterfactual)" value={eur(ev.data?.eur_protected)} accent="#2d9d78" />
        <Kpi label="Approved actions" value={String(ev.data?.approved_actions ?? 0)} />
        <Kpi label="Inference cost" value="€0" />
      </Flex>
      {proposed.map((a) => (
        <Card key={a.id} title={`#${a.id} · ${a.detail.exclude_community != null ? "Exclude community" : a.to_ad_set ? `Move ${eur(a.amount)}/day ${a.from_ad_set} → ${a.to_ad_set}` : `Hold back ${eur(a.amount)}/day on ${a.from_ad_set}`}`} right={<Text UNSAFE_style={{ fontSize: 12, opacity: 0.7 }}>cause: {HYPO_LABEL[a.detail.cause] ?? a.detail.cause}</Text>}>
          <Text>{a.reason}</Text>
          <Flex gap="size-400" marginTop="size-150" wrap>
            <div><div style={{ fontSize: 12, opacity: 0.7 }}>Wasted spend, no action</div><b>{eur(a.detail.wasted_without)}</b></div>
            <div><div style={{ fontSize: 12, opacity: 0.7 }}>Wasted spend, with action</div><b>{eur(a.detail.wasted_with)}</b></div>
            <div><div style={{ fontSize: 12, opacity: 0.7 }}>€ protected over {a.detail.days} days</div><b style={{ color: "#2d9d78", fontSize: 20 }}>{eur(a.eur_protected)}</b> <span style={{ fontSize: 12, opacity: 0.6 }}>± {eur(a.detail.eur_protected_sd)} over {a.detail.runs} paired runs</span></div>
            <div><div style={{ fontSize: 12, opacity: 0.7 }}>Revenue change</div><b>{a.detail.revenue_delta >= 0 ? "+" : ""}{eur(a.detail.revenue_delta)}</b> {!a.to_ad_set && a.detail.revenue_delta < 0 && <span style={{ fontSize: 12, opacity: 0.6 }}>(less spend also means fewer sales)</span>}</div>
          </Flex>
          <ButtonGroup marginTop="size-200">
            <Button variant="cta" onPress={() => decide(a.id, "approve")}>Approve</Button>
            <Button variant="secondary" onPress={() => decide(a.id, "reject")}>Reject</Button>
          </ButtonGroup>
        </Card>
      ))}
      {!proposed.length && <Text UNSAFE_style={{ opacity: 0.6 }}>No open proposals.</Text>}
      {decided.length > 0 && (
        <Card title="History">
          {decided.map((a) => (
            <div key={a.id} style={{ display: "flex", gap: 12, fontSize: 14, padding: "6px 0", borderBottom: "1px solid rgba(255,255,255,.06)" }}>
              <b style={{ color: a.status === "approved" ? "#2d9d78" : "#e34850", width: 80 }}>{a.status}</b>
              <span style={{ flex: 1 }}>#{a.id} {a.reason}</span>
              <b>{eur(a.eur_protected)}</b>
            </div>
          ))}
        </Card>
      )}
      <Text UNSAFE_style={{ fontSize: 12, opacity: 0.6 }}>
        € protected = wasted spend in the no-action counterfactual minus wasted spend with the action, over the same 7 simulated days, averaged over 5 paired forks with fixed seeds. Wasted spend = spend not covered by conversions at the campaign's max CPA.
      </Text>
    </Flex>
  );
}
