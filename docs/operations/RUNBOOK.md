# Running DashboardBridge in a customer's environment

The product runs on the customer's own machines. Nothing in the conversion path
reaches the network, and the licence is checked offline — an air-gapped customer
is a normal customer.

Two audiences, and they need different things:

* **The vendor** issues licences and ships hot fixes. Everything under
  *Issuing a licence* is yours and never leaves your machine.
* **The customer's operator** installs, configures and runs it. Everything under
  *Installing* and *Choosing a model provider* is theirs.

Every setting below is an environment variable read once at start-up, so a
change means a restart. That is deliberate: a deployment whose privacy mode or
licence can change under a running conversion cannot say what it did.

---

## Vendor: creating your keypair (once, ever)

```
t2pbi-license keygen --out ~/dashboardbridge-keys
```

The private half signs every licence you will ever issue. **If it leaks, anyone
can mint licences for your product; if you lose it, no existing licence can be
re-issued and every customer needs a new public key.** Back it up somewhere you
would back up a signing certificate.

`keygen` refuses to write inside a git work tree, and refuses to overwrite an
existing keypair — overwriting does not lose one licence, it orphans every
licence ever issued, because none verify against a new public half.

The public half ships with the application:

```
LICENSE_PUBLIC_KEY="$(cat ~/dashboardbridge-keys/vendor-public.pem)"
```

**Until this is set, every deployment reports itself unlicensed and refuses to
convert.** That is the intended failure: a build with no key cannot tell a real
licence from a forged one, so it trusts neither.

## Vendor: issuing a licence

```
t2pbi-license issue \
  --key ~/dashboardbridge-keys/vendor-private.pem \
  --customer "Northwind BI" \
  --days 365 \
  --features convert \
  --seats 5 \
  --out northwind.lic
```

`--expires 2027-01-31` instead of `--days` when the date is what was agreed.
Send the customer the `.lic` file; it is not a secret in the way the private key
is, but it is their paid credential, so send it the way you would send a
password.

Check one you have been sent back, or one you are about to send:

```
t2pbi-license inspect --file northwind.lic \
  --public-key ~/dashboardbridge-keys/vendor-public.pem
```

A tampered licence is reported as **forged**, never as expired — telling someone
their forged licence has run out sends them to renew something that was never
valid.

### Renewal

Issue a new licence with the same customer name and a later expiry, and have the
operator replace the file and restart. There is no revocation: an already-issued
licence is valid until its date. Match the licence length to what was paid for
rather than issuing long ones and expecting to withdraw them.

---

## Customer: installing a licence

Point the deployment at the file:

```
LICENSE_FILE=/etc/dashboardbridge/northwind.lic
```

or paste the token itself, for a container that mounts no files:

```
LICENSE_KEY="<the contents of the .lic file>"
```

There is **no route to install a licence over HTTP**, by design. Installing one
is putting a file on the machine and restarting — an operator's job with an
operator's permissions. An endpoint that accepted a licence would be an endpoint
that accepted a forged one to test against.

`GET /api/v1/license` reports what the deployment thinks it has. It never
returns the token.

### What expiry actually stops

**Converting.** Projects already converted stay open, with their reports and
their flags. Holding work someone has paid for hostage does not sell a renewal.
The application warns in the interface before the date, not on it.

---

## Customer: the first account, and everyone after

Accounts are local to this deployment. There is no vendor-side directory to
authenticate against, which is what "runs in your environment" has to mean - and
an air-gapped customer must still be able to add a colleague on a Tuesday.

### The first administrator

Set these and restart. They apply **only** when no account exists at all:

```
BOOTSTRAP_ADMIN_EMAIL=you@yourcompany.example
BOOTSTRAP_ADMIN_PASSWORD=<at least 12 characters>
```

Everything that touches a workbook, a project or a conversion requires a signed-in
account. Only three things are reachable before signing in: the health check, the
licence status (so the sign-in page can say a licence has lapsed), and signing in
itself.

There is deliberately **no page** that creates the first administrator. An
endpoint that makes one when the table is empty makes one on any deployment
whose database has not finished migrating. Same shape as the licence: set it
where the process reads it, restart, and the deployment is usable.

Once anyone exists these variables do nothing, so one left behind in a compose
file cannot re-create an administrator somebody deliberately removed. Remove
them after the first start anyway.

### Everyone else

An administrator adds people in the application. Two facts about accounts that
are decisions rather than mechanics:

* **Everyone converts.** The only privilege is administrator, which adds and
  deactivates people. There is no viewer/editor/owner vocabulary, because
  nobody has asked for one and permission models are very hard to withdraw once
  a customer has configured one.
* **Leavers are deactivated, not deleted.** A project records who converted it.
  Deactivating ends their sessions immediately and frees their seat.

### Seats

The licence states a seat count and it is enforced against **active** users.
Deactivating someone frees their seat at once - you are not charged for people
who have left. Adding a person beyond the count is refused with the number in
the message.

### Sessions

A session lasts 12 hours, and ends after 2 hours idle. The cookie is `httpOnly`,
so no script on the page can read it, and `SameSite=Lax`.

The cookie is marked `Secure` only when the deployment is reached over https - a
`Secure` cookie on a plain-http install is never sent at all, and the result is
a login that silently does nothing. **Put it behind TLS in production**, and
serve the application and its API from the same origin.

---

## Customer: choosing a model provider

AI is optional. With no provider configured, every AI path is **absent** from the
interface rather than shown and disabled — an offer that cannot be honoured is
worse than no offer. Conversion is fully deterministic without it.

Two providers ship, and which one to use is a question about the customer's
environment rather than about the product.

### A model on the customer's own hardware (Ollama)

```
AI_PROVIDER=ollama
AI_HOST=127.0.0.1
AI_PORT=11434
AI_MODEL=llama3.1
```

Needs no credential. This is the one that keeps working under
`PRIVACY_MODE=local_only`, because nothing leaves the machine.

### A model behind an OpenAI-compatible endpoint

```
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://your-endpoint/v1
AI_MODEL=gpt-4o-mini
AI_API_KEY=...            # read through the secret provider, see below
```

Anything speaking the `/chat/completions` shape — Azure OpenAI, vLLM, a
gateway — works here. **Refused under `PRIVACY_MODE=local_only`**, and the
refusal is reported rather than silently resolved in either direction: ignoring
it would read as "AI is off", honouring it would send a workbook off the machine.

### Where the key comes from

`AI_API_KEY` is read through the secret provider (`SECRETS_PROVIDER`, default
`env`). The other backends — Key Vault, Secrets Manager, Vault — are declared
and **raise** rather than falling back to the environment, so a deployment
cannot believe its keys are in a vault while they sit in its compose file.

There is no write path for the key. `GET /api/v1/settings/ai` reports whether one
is *configured* and whether the provider is *available*, which are different
facts with different remedies: "you have not set this up" and "you set it up and
it is not running" send a person to different places. It never returns the key,
nor a masked prefix — a prefix leaks the length and usually the first characters.

> **Not yet verified against a real model.** Every AI path in this product has
> been exercised through `MockProvider` only. The provider code, the router, the
> prompt fencing and the acceptance gauntlet are all tested; "a real model
> returns something useful" is not. Treat the first run against a live endpoint
> as a test, not as a deployment.

---

## Customer: privacy mode

```
PRIVACY_MODE=local_only            # default
PRIVACY_MODE=enterprise_private
PRIVACY_MODE=standard
```

`local_only` is the default and the strongest: no workbook content leaves the
machine, and a remote model provider is refused rather than used. The mode is
reported in the interface in the user's terms — where the file goes — not as an
enum they would have to look up.

---

## Other settings worth knowing

| Variable | Default | What it is |
| --- | --- | --- |
| `MAX_UPLOAD_SIZE_MB` | `500` | Refused before the body is read, not after |
| `REQUIRE_MALWARE_SCAN` | off | When on, an unscanned upload is refused; `NOT_SCANNED` is never treated as clean |
| `RATE_LIMIT_WRITE_PER_MINUTE` | `60` | Sliding window, weighted by cost |
| `RATE_LIMIT_READ_PER_MINUTE` | `600` | |
| `ARTIFACT_STORAGE_DIR` | temp | Where uploads and generated projects live |
| `APP_ENV` | `development` | |

---

## Shipping a hot fix

Not yet designed. Today an upgrade is a new build and a restart; the licence and
the artifact storage survive it, because both live outside the application
directory. A customer on an air-gapped network needs the build handed to them,
which is the constraint any answer here has to satisfy.

---

## Known limits, stated rather than discovered

* **Filters are reported, not converted.** A Tableau filter that restricts data
  is listed in the migration report with its values named and marked as manual
  work. The code to write a real Power BI filter exists and is tested against
  Power BI Desktop's own serializer, and is **off** until a Desktop has opened a
  project containing one.
* **The model carries schema, no rows.** Power BI Desktop will say "some of the
  tables have incomplete or no data", correctly. Each data source is reported
  with its kind and its path so the connection can be repointed.
* **No generated `.twb` has been opened by Tableau Desktop.** The Power BI
  direction has been opened and rendered by Power BI Desktop; the Tableau
  direction has not been opened by anything.
