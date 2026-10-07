// Live matches with plain Node 18+ fetch, no dependencies.
// Run: RAPIDAPI_KEY=... node examples/js/live_scores.mjs
const host = "cricbuzz-cricket.p.rapidapi.com";
const res = await fetch(`https://${host}/matches/v1/live`, {
  headers: { "x-rapidapi-key": process.env.RAPIDAPI_KEY, "x-rapidapi-host": host },
});
if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
const data = await res.json();
for (const group of data.typeMatches ?? []) {
  for (const series of group.seriesMatches ?? []) {
    for (const m of series.seriesAdWrapper?.matches ?? []) {
      const i = m.matchInfo;
      console.log(`${i.matchId}  ${i.matchFormat}  ${i.team1.teamSName} v ${i.team2.teamSName}  ${i.status ?? ""}`);
    }
  }
}
