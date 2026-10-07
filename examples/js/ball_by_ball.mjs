// Every delivery of an innings. Run: RAPIDAPI_KEY=... node examples/js/ball_by_ball.mjs 149618 1
const host = "cricbuzz-cricket.p.rapidapi.com";
const [matchId = "149618", innings = "1"] = process.argv.slice(2);
const res = await fetch(`https://${host}/mcenter/v1/${matchId}/ballsGraph?iid=${innings}`, {
  headers: { "x-rapidapi-key": process.env.RAPIDAPI_KEY, "x-rapidapi-host": host },
});
if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
const { balls = [] } = await res.json();
balls.sort((a, b) => a.timestamp - b.timestamp); // the API returns newest first
const overs = new Map();
for (const b of balls) {
  const over = Math.floor(b.overNum) + 1;
  overs.set(over, [...(overs.get(over) ?? []), b.ballLabel]);
}
for (const [over, labels] of overs) console.log(`over ${String(over).padStart(2)}: ${labels.join(" ")}`);
console.log("total runs:", balls.reduce((s, b) => s + b.totalRuns, 0));
