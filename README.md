# X1 LP Profit Bot

X1 market monitoring, read-only route quotes, and a bounded GOOGL.X premium seller.
The seller constructs and simulates protected swaps from current on-chain pool
accounts. It signs and submits only when explicitly started with `--live`.
It sells token inventory; LP fee collection and liquidity withdrawal are not implemented.

## Automatic GOOGL.X seller

### Local dashboard

```bash
python3 -m lp_profit_bot.dashboard
```

The dashboard enables its controls automatically in a same-origin browser session. Start, Stop, conversion, purchase, and bridge actions still require their existing confirmation and execution checks. The server binds only to loopback, checks the request origin, and uses an HTTP-only session cookie for control requests. Anyone who can use the local dashboard in this OS session can access these controls. Local state files are stored in a directory restricted to the current OS user.

### Automatic USDC.X bridge to Solana

The bridge worker sends only verified USDC.X from finalized automatic XNT conversions
and direct GOOGL.X sales. It uses the existing bot wallet on both chains because
Warp Bridge currently bridges to the same public key that signs the X1 transfer.
The Solana destination is the locally configured bot wallet's public address.
The bridge route, program, token mints, fee, limits, and guardian threshold are
checked against the current Warp Bridge configuration before every transfer.
The current bridge minimum is 10 USDC.X and the flat fee is 1 USDC.X; the worker
refuses fees over 1 USDC.X and sends no more than 100 USDC.X per batch.

Preview one batch without signing:

```bash
python3 -m lp_profit_bot.auto_bridge
```

To run the worker continuously after reviewing the dry run:

```bash
python3 -m lp_profit_bot.auto_bridge --live --watch
```

Live mode signs and broadcasts without further prompts. Each attempt is simulated
and reserved in `state/auto-bridge-journal.json` before broadcast. The worker waits
for both X1 finality and a finalized Solana USDC receipt before another batch.
Unknown or failed transfers retain their reservation and stop further sends until
the journal and chain records are reviewed. Existing wallet USDC.X that did not
come from the eligible sale/conversion journals is excluded. Keep some XNT in the
wallet for X1 transaction fees. The worker is separate from the dashboard and
the existing conversion worker; run those independently if desired.

The dashboard also has a **USDC bridge** panel. Enter 10–100 USDC.X, select
**Preview bridge**, review the fee and same-wallet Solana destination, then
select **Confirm USDC.X → Solana USDC** within 30 seconds. Previews are single
use. Manual transfers share the journal and transaction lock with the automatic
worker, so one pending transfer blocks another. The bridge log shows X1 and
Solana transaction links and finality status. **Stop bridge** stops future
automatic attempts but cannot cancel a submitted transfer. Local worker events
are appended to `state/auto-bridge.log`.

### Solana stock purchase and bridge to X1

`python3 -m lp_profit_bot.buy_stock_bridge` previews GOOGL by default. Add
`--stock aapl`, `spy`, `spcx`, `tsla`, `meta`, `coin`, `pltr`, `amd`, or `nvda` to select
another supported stock. For example:

```bash
python3 -m lp_profit_bot.buy_stock_bridge --stock tsla --amount 25
```

The command previews the requested USDC amount (11 by default, with up to six
decimal places) and checks that Jupiter's protected minimum output clears the
selected stock's *current* Warp Bridge minimum. With
`--live`, it signs a Solana USDC → selected stock swap from the bot wallet,
verifies its finalized receipt, then bridges only those purchased tokens to the
same wallet on X1. Each stock has a separate journal in `state/`;
GOOGL keeps its existing `state/googlx-buy-bridge-journal.json`. If a send or
receipt is uncertain, rerun the command with the same `--stock` to check status;
it never blindly repeats either transaction. A completed bridge can be followed
by another purchase with `--new-purchase`; the previous attempt remains in the
journal. The amount is limited by the available Solana USDC and current bridge
route limits. The 0.5% swap slippage cap, 1% price-impact limit, bridge mint
and fee checks, and Solana fee ceiling remain fixed in code. The dashboard's **Buy & bridge** panel offers
the same selected-stock amount preview and a separate confirmation. A successful submission starts a background watcher that waits
for Solana finality, bridges the purchased tokens, and verifies the X1 receipt.
The panel shows journal state and transaction links. If tracking stops while a
transaction is pending, preview that same stock again to check and continue its
recorded stage; do not assume the first transaction failed.
Its purchase timeline lists each attempt from Solana submission and finality
through bridge submission, bridge finality, and the verified X1 receipt, with
receipt links. New journal entries record when each stage was observed; older
entries show "Time not recorded" where a stage timestamp is unavailable. A
warning identifies the affected stock and last confirmed step if a transaction
fails, the background tracker stops, or a pending stage exceeds a display
threshold. Preview errors and completed transfers are announced through accessible
status messages. These alerts are informational; they never retry or submit a
transaction automatically.
The purchase flow has isolated tests for supported stock routes, bridge minimums,
repeat purchases, pending-stage tracking, and the dashboard preview/confirmation
endpoints. Run them without signing or broadcasting a transaction with:

```bash
python3 -m unittest tests.test_buy_googl_bridge tests.test_dashboard -q
```

These mocked tests verify the application paths; a current Jupiter quote and a
completed live bridge still depend on external services and wallet balances.
The previous `buy_googl_bridge` module remains available and accepts the same
options.

AAPL buy-and-bridge uses Solana mint
`XsbEhLAtcf6HdfpFZ5xEMdqW8nfAvcsP5bdudRLJzJp`, X1 mint
`u7i4awutsHa9qcy6YdDQKfjER16i9fx4PRhG4ZqUXZ5`, and bridge-program escrow
`rUKQ9E2yWqTxDQ9DWBZtBha2REkS5G3KeUtA3uBFAFn`. The code derives the escrow
from the bridge program and Solana mint and rejects the transaction if it no
longer matches. The dashboard monitors AAPL.X balance, X1/XNT pool
`4uX1ZyDNVAjpozzsuGMcaHJeSXfpB1TGrckHUkNkB2TX`, CoinGecko reference price,
spot premium, liquidity, and estimated USD value. AAPL.X is included in the
shared automatic stock-sale policy and its verified XNT proceeds are eligible
for the proceeds-only automatic conversion.

The **Actual proceeds history** lists every journaled stock sale and XNT conversion using finalized on-chain receipts. It shows actual input, net native XNT received, actual USDC.X received, network fees, and other native costs such as rent. Pending or unverifiable receipts show blank amounts. XNT received is already net of network fees. Conversion output is reported separately because manual conversions may include unrelated wallet funds or combine sales. These receipts are proceeds, not cost-basis profit. Historical receipts are cached separately in `state/proceeds-history.json`; updating this history never signs, submits, or changes trading journals.

The **Transaction terminal** shows recorded sales/conversions and live worker activity, refreshes every 5 seconds, and checks pending signatures directly on-chain. Filter by script, turn off **Follow latest** to read older entries, or open explorer links to inspect actual proceeds. Imported trade timestamps are submission times; status changes observed during the session appear as new entries. The feed retains 250 public entries and never displays raw logs, keys, or signed transaction payloads.

The **Start automatic conversion** button in the **XNT → USDC.X** panel starts the existing proceeds-only worker with its reserve protection. Duplicate starts are blocked; a failed automatic conversion requires journal review before restart. The button does not convert unrelated XNT or reset accounting.

The **Running scripts** control center shows each worker separately: GOOGL.X, SPY.X, SPCX.X, TSLA.X selling, and automatic proceeds conversion. Each has a **Stop** button, and **Stop all scripts** ends all five workers while leaving the dashboard online. Stop preserves caps and journals and does not cancel transactions already broadcast. Process identity is checked against the fixed module, project directory, and current user before signaling; process handles prevent PID reuse from targeting unrelated programs. Stopping does not restart a worker automatically.

Open **http://localhost:8795** in your browser. On WSL, use your Windows browser
on the same computer. Use `--port 8796` if the default port is occupied. The server
binds only to `127.0.0.1`. It shows wallet balances, pool/reference prices and their
freshness, seller process status, cap usage, journal transactions, and the last
unsigned simulation. Market data refreshes every 30 seconds and the screen every
5 seconds. The chart holds up to one hour of observations in dashboard memory.
The overview, wallet summary, and strategy cards show estimated USD values
beside available stock and USDC.X balances. Stock estimates multiply the wallet
quantity by a current X1 pool spot price; GOOGL.X uses its USDC.X pool with
USDC.X treated as $1. USDC.X uses the same $1 assumption. The estimates are
not executable quotes or profit figures. Stale or missing prices show an
unavailable estimate. XNT has no current USD price in the dashboard, so its
estimated value is unavailable. Confirmed sold quantity is historical activity,
not a wallet balance.

The SPCX.X watchlist panel monitors mint `CCqoyVud4QNCccV9EJtWEFPaC6jBaGJsaFTnyD8Ss47m` in its XNT pool, showing wallet balance, pool price, CoinGecko `spacex-xstocks` reference, and liquidity. It refreshes every 60 seconds and suppresses the premium when stale. SPCX.X and TSLA.X also have separate automatic sellers and Start/Stop controls under the [shared stock policy](STOCK_POLICY.md). TSLA.X mint: `47wNUaHJyuiknQswU5qsfYKjaZ9ijueRB63ZrsxuRb4F`.

The SPY.X watchlist panel monitors mint `5Z7K1BaM36ubfNHkXbiDm5GW3KGzVSt3DFxD2b7p4VtJ` in its XNT pool. It displays the X1.Ninja USD spot price, CoinGecko SP500 xStock reference, wallet balance, and pool liquidity every 60 seconds. It requires the configured Ninja API key. Stale data suppresses the premium; The separate SPY.X seller has no total or per-trade amount cap and can sell current and future deposited inventory, with native XNT proceeds. It uses a separate journal and only sells above the reference after costs and a 5% XNT valuation margin. Its status and confirmed sold total appear in the panel. **Sell SPY.X → XNT** starts this seller with the existing price and cost protections; while active the button reads **SPY.X → XNT · Running**. Running and halted SPY.X sellers cannot be started again through the button.

Automatic conversion runs with `python3 -m lp_profit_bot.auto_convert --live --watch` (omit `--live` for simulation). It converts only verified net SPY.X, SPCX.X, and TSLA.X sale proceeds, including completed sales, and deducts all journaled conversions and their costs. It protects the native balance recorded immediately before the first included stock sale. Receipts are cached in `state/auto-convert-receipts.json`; the existing conversion journal reserves each amount before broadcast. Pending conversions block another trade, failed automatic conversions stop the worker, and restarts cannot reset the proceeds budget. It checks every 15 seconds, uses at most 25 XNT per batch, and accumulates remainders below 0.05 XNT plus the 0.01 XNT cost allowance. It applies the existing 0.5% slippage bound. The dashboard shows whether automation is active, its protected reserve, and unconverted proceeds. Closing the page does not stop it.

The **Manual conversion** section in the **XNT → USDC.X** panel accepts an explicit amount, previews a 0.5%-slippage-protected minimum, and submits only after **Confirm XNT → USDC.X**. Quotes expire after 30 seconds and can be used once. Each conversion is simulated and journaled before submission; unresolved transactions block another native swap. Native XNT swaps use a temporary wrapped account that is closed in the same transaction. A 0.01 XNT cost allowance and fee/rent reserve apply.

Stock seller commands (default is simulation; use the approved policy in [STOCK_POLICY.md](STOCK_POLICY.md)):

```bash
python3 -m lp_profit_bot.spy_seller
python3 -m lp_profit_bot.spy_seller --live --watch
python3 -m lp_profit_bot.spcx_seller --live --watch
python3 -m lp_profit_bot.tsla_seller --live --watch
```

The SPY.X journal is `state/spy-seller-journal.json`; prior sale history is preserved when migrating from the original capped policy. The process stops on errors and keeps pending/failed reservations. Run live mode only under the authorized sale policy.

Click **Start selling** to launch the live GOOGL.X → USDC.X seller with its existing price checks and 0.005 batch limit. There is no lifetime sale cap. Opening the dashboard alone does not trade. An existing seller or a halted journal prevents another start. Keys stay local. The seller continues after the dashboard closes; output is saved in `state/seller-dashboard.log`. The button does not reset the journal or stop an existing seller.
Run it in a separate terminal while the seller runs. Transaction rows show the
**protected minimum**, not actual proceeds; links open the explorer. USDC.X wallet
balance includes any external transfers and is not labeled profit. Pending and
failed quantities count toward the total reserved cap. File routes are explicitly
allowlisted; key files, API credentials, and arbitrary project files are never served.

Existing seller processes remain undisturbed. Exact live/simulation mode telemetry
appears after starting the updated seller; older processes show running status with
mode unavailable. Seller process state is checked through its lock file, not inferred
from past trades. Last telemetry older than two minutes is ignored.

Run one unsigned simulation:

```bash
python3 -m lp_profit_bot.seller
```

Monitor and simulate every minute without trading:

```bash
python3 -m lp_profit_bot.seller --watch
```

To start unattended real sales with the configured bot wallet:

```bash
python3 -m lp_profit_bot.seller --live --watch
```

`--live` authorizes signatures and broadcasts without further per-trade prompts.
Keep the terminal and computer running. Ctrl+C stops future attempts but cannot
cancel a submitted transaction. No background service is installed or started.

The seller is restricted to the public address derived from the local bot keypair,
the specified GOOGL.X/USDC.X pool, and batches no larger than **0.005 GOOGL.X**.
There is **no lifetime quantity cap**: while live watch mode runs, it may sell
current or future deposits whenever the price and cost checks pass. Existing
sale journals retain their entries and migrate from the former 0.07 cap without
resetting transaction history. Pending submissions block another sale, and a
failed sale halts the worker for review. It never buys tokens or executes
triangular arbitrage. It values USDC.X at $1 for comparison; this is an assumption,
not a redemption guarantee. Reference-based surplus is not original-cost profit.

Each cycle checks the CoinGecko reference timestamp (maximum 300 seconds old),
loads coherent pool and wallet accounts, checks token mints/programs/extensions,
reads the pool's trade fee, and estimates the swap with integer arithmetic. It
reduces the batch to avoid pushing the estimated ending pool price below the
reference. Fees reduce estimated output. The enforced minimum output exceeds
reference value plus a conservative **0.01 XNT** cost allowance, converted using
the on-chain XNT/USDC.X reserves with 5% headroom. It also enforces a 0.5% maximum
output reduction relative to its pool estimate. These percentages do not override
the requirement to exceed reference value after the cost allowance.

Transactions are constructed locally with fixed compute-budget instructions,
idempotent creation of the wallet's USDC.X token account, and one protected XDEX
swap. API-provided transaction bytes are never signed. Unsigned simulation must
show the exact GOOGL.X debit, sufficient USDC.X credit, and native costs within
the allowance. Snapshots expire after 30 seconds, and the reference is checked
again before signing. The snapshot reference is not an on-chain price oracle;
reference prices, USDC.X value, or pool conditions can still change before execution.
Failed transactions may consume network fees. No profit is guaranteed.

`state/seller-journal.json` reserves input before broadcasting and tracks each
signature. A process lock prevents two local seller instances. No new sale occurs
until a pending signature is finalized. Unknown/dropped transactions stay pending;
the seller never blindly resends or releases their reserved amount. On-chain failure
halts the seller. API/RPC or malformed-data errors stop the process. Inspect any
pending signature in the explorer before recovery; **do not delete or reset the
journal**, even after restarting. The journal is part of the spending-limit control.

Only `--live` activates execution; `state/execution-policy.json` is a description
of the fixed policy, not a runtime enable switch. The default command does not
load the signing key. Dependencies are installed in this workspace; on another
machine use `python3 -m pip install '.[trading]'` in a virtual environment. `curl`
is also required. Latest unsigned simulation details are saved in
`state/seller-last-simulation.json`.

## Target network

### Separate bot wallet

```bash
python3 -m lp_profit_bot.wallet --create
python3 -m lp_profit_bot.wallet
```

For a wallet app that accepts a Base58 private key, run
`python3 -m lp_profit_bot.wallet --export-private-key` in your own terminal.
This explicitly prints the secret key. Import it directly into your wallet;
never paste it into chat or an online converter. Default commands show only the
public address.

The first command creates a separate X1-compatible Ed25519 keypair once. Repeating
it preserves the existing key. The second prints only its public address. The key
is stored in `.secrets/bot-wallet.json` in Solana's 64-byte JSON keypair format,
with file permissions `600` inside a `700` directory, excluded from Git. It is
unencrypted local signing material: keep a private backup, never paste its contents
into chat, and do not delete it after funding. The public metadata is recorded in
`state/bot-wallet.json`; the original wallet reference remains in `state/wallet.json`.

The `cryptography` dependency is already available in this workspace. On another
machine, install wallet support with `python3 -m pip install '.[wallet]'` inside
a virtual environment. Wallet creation is entirely local and makes no network calls.

Wallet setup alone does not enable trading. Use the separate seller commands
above. The initial audit found a zero minimum output in an XDEX-prepared
transaction; the seller builds its own transaction with enforced output bounds.

The user's public wallet address is recorded locally in `state/wallet.json`,
which is excluded from Git. This is a reference for future wallet integration;
the market monitor does not load it or sign transactions. The separate bot keypair
is stored locally as described above.

This project targets the X1 blockchain described at [docs.x1.xyz](https://docs.x1.xyz/).
X1 is compatible with the Solana Virtual Machine (SVM), so the planned integration
will use SVM accounts, programs, and transaction signing. The chain selection is
confirmed; the live seller is restricted to XDEX GOOGL.X inventory sales into USDC.X.

[XDEX](https://xdexdocs.gitbook.io/xdex) is a potential liquidity protocol on X1,
whose market data can now be fetched through X1.Ninja. On-chain pool account layouts and withdrawal
instructions must come from the selected protocol. The existing snapshot simulator
remains independent of those layouts.

## Run

Requires Python 3.10+; the simulator has no external dependencies.

```bash
cd /path/to/lp-profit-bot
python3 -m lp_profit_bot
python3 -m lp_profit_bot --watch --interval 30
python3 -m unittest discover -s tests -v
```

Edit `examples/positions.json` to try different snapshots. Watch mode reloads
that file and emits a JSON event on first observation and whenever a position's
decision changes. It does not fetch prices. Deduplication is in memory and resets
on restart. Invalid snapshots stop the process with a nonzero exit code.

## Live pool data with X1.Ninja

Use your key from [X1.Ninja key management](https://x1.ninja/developers/keys).
To save it once and avoid entering it on every run:

```bash
python3 -m lp_profit_bot --setup-key
```

Paste the key at the hidden prompt and press Enter. It is saved in the project's
`.secrets/ninja-api-key` file, excluded by `.gitignore`, with file permissions
`600` and directory permissions `700` (only your user has access). This is a local
plaintext file, not encrypted storage. Run `--setup-key` again to replace it, or
delete that file to forget it. An existing `X1_API_KEY` environment variable takes
precedence over the saved key; use `unset X1_API_KEY` to use the saved key instead.

Run the command below. When the bot asks for your key, paste it and press Enter.
If a saved key or environment variable is available, there is no prompt. Otherwise,
the prompted key stays invisible and is used only for that run; it is not saved.
For unattended runs, set `X1_API_KEY` in the environment instead. The application
does not automatically load `.env` files.

```bash
cd /path/to/lp-profit-bot
python3 -m lp_profit_bot --pools --limit 10
```

Fetch one pool by replacing `POOL_ADDRESS` with its address:

```bash
python3 -m lp_profit_bot --pool POOL_ADDRESS
```

These commands print API JSON and make one request per invocation. The list
command fetches a single page, not every pool. Requests time out after 20 seconds; API failures stop the command without
automatic retries. Redirects are blocked to avoid forwarding the API credential.
Authentication uses the documented bearer header at `https://api.x1.ninja`.
See the [API documentation](https://x1.ninja/developers) for available data.

Pool market data alone does not establish your LP ownership or profit. It is not
yet connected to the snapshot profit engine. Your position balances, contributions,
withdrawals, and desired profit-taking action are still needed for live decisions.
This API integration does not sign or submit transactions.

### Monitor the selected GOOGL.X / USDC.X pool

```bash
python3 -m lp_profit_bot --pool 8MFEMQNdgES25bfhNuo2xAmbES6kiPHhKD27cZwkT2dj --watch --interval 30
```

Enter the API key once when prompted. Press Ctrl+C to stop. Each check prints a
compact JSON observation with price, liquidity, and freshness. `--max-age 300`
(the default) flags data older than five minutes as `STALE`. Missing or invalid
timestamps show `UNKNOWN_FRESHNESS`; future timestamps are flagged separately.
Freshness uses the pool's `lastSyncedAt`, not the API's overall update timestamp.
These statuses describe data freshness, not whether a pool is safe to trade.
Minimum live polling interval is five seconds. Errors stop monitoring; the bot
never reuses the previous quote after a failed request. A pool observation does
not establish ownership, a deposit cost, an executable exit price, or profit.

## Profit calculation

### Compare GOOGL.X against the reference price

```bash
python3 -m lp_profit_bot --compare-googl
python3 -m lp_profit_bot --compare-googl --watch
```

The first command checks once; the second checks every 60 seconds using your
saved X1.Ninja key. It compares your selected pool with CoinGecko's
`alphabet-xstock` USD reference, the reference source used by
[Prism's GOOGL view](https://x1prism.com/stonks#googl). The bot calls CoinGecko
directly and does not scrape or depend on Prism's page. CoinGecko is an aggregated
xStock price, not a directly executable Solana quote or the underlying stock price.

The output shows both prices and `(X1 price / reference price - 1) * 100`.
It also shows each feed's data age and the configured freshness limit. A stale
status does not stop polling: comparisons resume automatically when both feeds
provide fresh data. Restart an already-running process to load code updates.
A positive gap means an X1 premium; a negative gap means an X1 discount. If either
source is stale, future-dated, or missing its update timestamp, the gap is suppressed
and the status is `DATA_NOT_FRESH`. `--max-age` defaults to 300 seconds. Token mint
addresses and the pool address are checked before comparing. Neither fees,
slippage, bridging costs, nor USDC.X redemption value are modeled. These are
observations, not trade signals or profit estimates; no transactions are submitted.

The public CoinGecko endpoint worked without a key during setup. Access and rate
limits may vary. An optional `COINGECKO_DEMO_API_KEY` environment variable is supported
and is sent only to CoinGecko; the Ninja key is sent only to X1.Ninja. API errors stop
the monitor, without reusing old prices or automatically retrying. See the
[CoinGecko API documentation](https://docs.coingecko.com/demo/reference/simple-price).

### Snapshot profit calculation

All monetary fields use USD and decimal arithmetic:

```
net profit = current principal value + unclaimed fees + historical withdrawals
             - total contributions - estimated exit cost
return percent = net profit / total contributions * 100
```

Principal value must exclude unclaimed fees. Historical withdrawals include fees
already collected and principal already withdrawn. Contributions include all
deposits for that position. Supply consistent valuations and complete cash-flow
history. Exit cost should include estimated transaction and conversion costs.
This is an absolute cash-flow return, not an annualized return or a comparison
against holding the deposited tokens. Taxes are not modeled.

The demo's 10% threshold is an arbitrary example, not a recommended strategy.
`TARGET_REACHED` is a simulation result, not an executed action.

## Live integration decisions

### Read-only XDEX route quotes

```bash
python3 -m lp_profit_bot.quotes
```

This checks three token cycles in both directions, starting each with 1 wrapped
XNT: XNT/GOOGL.X/USDC.X, XNT/GOOGL.X/JACK, and XNT/GOOGL.X/SPCX.X. It requires
`curl`, makes up to 18 public quote requests, and needs neither a private wallet
key nor the Ninja API key. Intermediate amounts are rounded down to token
precision. Detailed results are saved in `state/latest-route-quotes.json`.

The endpoint and human-unit parameters were identified in XDEX's public swap
frontend on 2026-09-19:
`GET https://api.xdex.xyz/api/xdex/swap/quote`, with `network=X1 Mainnet`,
`token_in`, `token_out`, `token_in_amount`, `is_exact_amount_in=true`, and
`slippage=0.5`. These frontend interfaces may change without notice.

These quotes are indicative, obtained sequentially, and are not a blockchain
transaction simulation. XDEX selects pools for each token pair: its response
exposes an AMM configuration address, not a verified pool address. The checker
does not claim to pin execution to the seven supplied pools. The response does
not expose a fee breakdown, chain slot, or minimum received amount; fee treatment
and quote freshness cannot be fully verified. Routes taking over 30 seconds to
quote are flagged. The displayed difference excludes network/priority fees,
account creation and wrapping costs, and further slippage. No result authorizes
execution or establishes guaranteed profit. No prepare/sign/send endpoint is called.

Before implementing a live adapter, choose:

- X1 liquidity protocol and the existing positions or public wallet address to monitor.
- Whether taking profits means an alert, collecting fees, or withdrawing liquidity.
- Target rules, polling frequency, and transaction cost/slippage limits.

The live adapter must obtain position balances, fee amounts, cash-flow history,
and current valuations. Transaction execution will need quote freshness checks,
simulation, persistent transaction tracking, and reconciliation after restart
before enabling automatic actions. Wallet signing configuration depends on the
selected chain; no private keys are needed for this starter.

## Additional X1 stocks

NVDA.X, META.X, COIN.X, PLTR.X, and AMD.X have wallet/price monitoring, individual
Start/Stop controls, transaction activity, and finalized proceeds history.
They use the shared 5% valuation buffer and price/cost protections. Their verified
XNT sale proceeds participate in the existing USDC.X converter. Reference requests
for these stocks are batched and cached for 60 seconds, preserving source timestamps.
NVIDIA uses the confirmed X1 mint `4JfDXUw8N7b1VJ1og1K3Nc4Z6nwtWxWJUSQKYBcdsiJz`.
