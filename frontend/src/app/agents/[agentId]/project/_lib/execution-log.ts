export type EvidenceRecord = Record<string, unknown>

export function evidenceRecord(value: unknown): EvidenceRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as EvidenceRecord)
    : {}
}

export function evidenceRecords(value: unknown): EvidenceRecord[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is EvidenceRecord =>
          item !== null && typeof item === 'object' && !Array.isArray(item),
      )
    : []
}

/** Associate retained executions with model requests by name and occurrence.
 * Records without a matching request stay separate; do not invent chronology.
 */
export function executionLog(value: unknown) {
  const evidence = evidenceRecord(value)
  const events = evidenceRecords(evidence.tool_trace)
  const used = new Set<number>()
  const calls = evidenceRecords(evidence.model_calls).map((call) => {
    const returns = evidenceRecords(call.returns)
    const tools = returns
      .flatMap((response) => evidenceRecords(response.tool_calls))
      .map((request) => {
        const index = events.findIndex(
          (event, index) => !used.has(index) && event.name === request.name,
        )
        if (index >= 0) used.add(index)
        return { request, event: index >= 0 ? events[index] : undefined }
      })
    return { call, returns, tools }
  })
  return { evidence, calls, otherTools: events.filter((_, index) => !used.has(index)) }
}
