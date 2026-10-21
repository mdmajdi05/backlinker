import * as React from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  Label,
  MetricTile,
  useToast,
} from "@autobacklinker/ui";
import {
  api,
  apiClient,
  isMissingEndpoint,
  type AutoPilotState,
} from "../lib/api";
import { ErrorBlock, LoadingBlock } from "./common";
import { sendNativeNotification } from "../lib/backend";
import { formatNumber, titleCase } from "../lib/format";
import { OpportunityCategory } from "@autobacklinker/shared-types";

/**
 * The auto pilot of a project.
 *
 * When it is on, approving an opportunity in the registry queues the
 * submission right away - the task runs on this machine and only asks the
 * operator for something when the target site needs a detail that is still
 * missing.
 *
 * The panel never pretends that the feature works: when the local backend
 * does not know the endpoint yet, the switch is disabled and the reason is
 * written down.
 */

const CATEGORIES = Object.values(OpportunityCategory);

function errorText(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    return String((error as { message: unknown }).message);
  }
  return fallback;
}

export function AutoPilotPanel({ projectId }: { projectId: string }) {
  const toast = useToast();
  const [state, setState] = React.useState<AutoPilotState | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState<unknown>(null);
  const [enabled, setEnabled] = React.useState(false);
  const [categories, setCategories] = React.useState<string[]>([]);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.autoPilot.get(apiClient, projectId);
      setState(result);
      setEnabled(result.enabled);
      setCategories(result.categories);
      setLoadError(null);
    } catch (err) {
      setState(null);
      setLoadError(err);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const unsupported = Boolean(loadError) && isMissingEndpoint(loadError);
  const dirty =
    state !== null &&
    (state.enabled !== enabled ||
      state.categories.join("|") !== categories.join("|"));

  function toggleCategory(category: string) {
    setCategories((previous) =>
      previous.includes(category)
        ? previous.filter((item) => item !== category)
        : [...previous, category],
    );
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const result = await api.autoPilot.update(apiClient, projectId, {
        enabled,
        categories,
      });
      setState(result);
      setEnabled(result.enabled);
      setCategories(result.categories);
      toast.push(
        result.enabled
          ? "The auto pilot is on - approved opportunities are submitted automatically."
          : "The auto pilot is off.",
        "success",
      );
      void sendNativeNotification(
        "Auto Backlinker",
        result.enabled
          ? "The auto pilot of this project is on."
          : "The auto pilot of this project is off.",
      );
    } catch (err) {
      setError(errorText(err, "Could not save the auto pilot"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Auto pilot"
        description="Submit the approved opportunities without a click per site."
        action={
          state ? (
            <Badge tone={state.enabled ? "success" : "neutral"}>
              {state.enabled ? "On" : "Off"}
            </Badge>
          ) : null
        }
      />
      <CardBody>
        {loading && !state ? (
          <LoadingBlock rows={3} />
        ) : null}

        {loadError ? (
          unsupported ? (
            <Alert
              tone="warning"
              title="The backend does not support the auto pilot yet"
            >
              The local backend of this installation is older than the
              automatic submission. It can not queue the approved
              opportunities on its own - update the backend and reload this
              view.
            </Alert>
          ) : (
            <ErrorBlock
              message={errorText(loadError, "Could not load the auto pilot")}
              onRetry={() => void load()}
            />
          )
        ) : null}

        {state ? (
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <MetricTile
                label="Waiting"
                value={formatNumber(state.waiting)}
                tone="warning"
                hint="Opportunities that wait for a detail"
              />
              <MetricTile
                label="Submitted"
                value={formatNumber(state.submitted)}
                tone="success"
                hint="Opportunities that were submitted"
              />
            </div>

            <div>
              <Label className="flex items-center gap-2 text-content">
                <Checkbox
                  checked={enabled}
                  disabled={unsupported || saving}
                  onChange={(event) => setEnabled(event.target.checked)}
                />
                Submit the approved opportunities automatically
              </Label>
              <p className="mt-1 text-xs text-content-muted">
                Approving an opportunity queues the submission right away. The
                task then runs on this machine and keeps going on its own. If
                the target site asks for a detail that is still missing, the
                task waits for you in the queue - it does not fail.
              </p>
            </div>

            <div>
              <p className="mb-2 text-xs font-semibold text-content">
                Categories
              </p>
              <p className="mb-2 text-[11px] text-content-subtle">
                Only the opportunities of these categories are submitted
                automatically. Without a selection every category is used.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {CATEGORIES.map((category) => {
                  const active = categories.includes(category);
                  return (
                    <button
                      key={category}
                      type="button"
                      aria-pressed={active}
                      disabled={unsupported || saving}
                      onClick={() => toggleCategory(category)}
                      className={
                        active
                          ? "h-8 rounded-md border border-accent bg-accent-soft px-2.5 text-xs font-medium text-accent"
                          : "h-8 rounded-md border border-line px-2.5 text-xs font-medium text-content-muted transition-colors hover:bg-surface-sunken disabled:opacity-50"
                      }
                    >
                      {titleCase(category)}
                    </button>
                  );
                })}
              </div>
              {categories.length > 0 ? (
                <div className="mt-2 flex items-center gap-2">
                  <Badge tone="accent">
                    {categories.length} categor
                    {categories.length === 1 ? "y" : "ies"}
                  </Badge>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={saving}
                    onClick={() => setCategories([])}
                  >
                    Every category
                  </Button>
                </div>
              ) : (
                <p className="mt-2 text-[11px] text-content-subtle">
                  Every category is submitted automatically.
                </p>
              )}
            </div>

            {error ? (
              <Alert tone="danger" title="The auto pilot could not be saved">
                {error}
              </Alert>
            ) : null}

            <div className="flex items-center justify-end gap-2 border-t border-line pt-3">
              {dirty ? (
                <p className="mr-auto text-[11px] text-content-subtle">
                  There are unsaved changes.
                </p>
              ) : null}
              <Button
                variant="outline"
                disabled={saving || unsupported}
                onClick={() => void load()}
              >
                Reload
              </Button>
              <Button
                loading={saving}
                disabled={!dirty || unsupported}
                onClick={() => void save()}
              >
                Save
              </Button>
            </div>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}
