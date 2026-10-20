import * as React from "react";
import { Button, Card, CardBody, CardHeader, Field, Input, Tabs } from "@autobacklinker/ui";
import { useAuth } from "./lib/auth";
import { DesktopShell } from "./components/DesktopShell";

function SplashScreen() {
  return (
    <div className="flex h-screen w-screen items-center justify-center bg-surface-sunken">
      <p className="text-sm text-content-muted">Starting Auto Backlinker…</p>
    </div>
  );
}

function LoginScreen() {
  const { login, register, busy, error } = useAuth();
  const [tab, setTab] = React.useState("signin");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [name, setName] = React.useState("");
  const [localError, setLocalError] = React.useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLocalError(null);
    try {
      if (tab === "signin") {
        await login(email, password);
      } else {
        await register(name, email, password);
      }
    } catch (err) {
      setLocalError(
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : "Sign in failed",
      );
    }
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-surface-sunken p-6">
      <Card className="w-full max-w-md">
        <CardHeader
          title="Auto Backlinker"
          description="Sign in to the backend this desktop client is connected to."
        />
        <CardBody>
          <form onSubmit={submit} className="flex flex-col gap-3">
            <Tabs
              tabs={[
                { id: "signin", label: "Sign in" },
                { id: "register", label: "Create account" },
              ]}
              active={tab}
              onChange={setTab}
            />

            {tab === "register" ? (
              <Field label="Name" required>
                <Input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Jane Doe"
                  autoComplete="name"
                />
              </Field>
            ) : null}

            <Field label="Email" required>
              <Input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
              />
            </Field>

            <Field label="Password" required>
              <Input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete={
                  tab === "signin" ? "current-password" : "new-password"
                }
              />
            </Field>

            {localError || error ? (
              <p className="text-xs text-danger">{localError ?? error}</p>
            ) : null}

            <Button
              type="submit"
              loading={busy}
              disabled={!email || !password || (tab === "register" && !name)}
            >
              {tab === "signin" ? "Sign in" : "Create account"}
            </Button>
          </form>

          <p className="mt-4 text-xs text-content-subtle">
            The desktop app normally connects to its local backend without an
            account. If the login stays empty, start the local backend from the
            Settings page.
          </p>
        </CardBody>
      </Card>
    </div>
  );
}

export default function App() {
  const { status } = useAuth();

  if (status === "loading") return <SplashScreen />;
  if (status === "anonymous") return <LoginScreen />;
  return <DesktopShell />;
}
