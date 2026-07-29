import type { MaterialGraphSnapshot } from './types';

/**
 * A non-null snapshot is not, by itself, proof that a Graph run started.
 *
 * Open WebUI can keep a zero-value placeholder while an ordinary chat is
 * active. Rendering that placeholder as a terminal workflow would claim that
 * work ran when it did not. Only execution topology or checkpoint activity is
 * sufficient to leave the idle state.
 */
export const hasStartedMaterialGraphWorkflow = (
	snapshot?: MaterialGraphSnapshot | null
): snapshot is MaterialGraphSnapshot => {
	if (!snapshot) return false;

	const workflow = snapshot.workflow ?? snapshot.workflow_definition;
	return Boolean(
		snapshot.current_node ||
		snapshot.checkpoint_id ||
		snapshot.form_id ||
		(snapshot.nodes?.length ?? 0) > 0 ||
		(snapshot.edges?.length ?? 0) > 0 ||
		(snapshot.logs?.length ?? 0) > 0 ||
		(workflow?.nodes?.length ?? 0) > 0 ||
		(workflow?.edges?.length ?? 0) > 0
	);
};
