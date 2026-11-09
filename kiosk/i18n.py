"""Touchscreen-only translations; the CLI and wire protocol stay in English."""
STRINGS = {
    "scanner_off": ("Scanner offline", "Scanner déconnecté"),
    "ready_full": ("Ready  /  paper loaded", "Prêt  /  papier chargé"),
    "ready": ("Ready  /  load paper", "Prêt  /  chargez le papier"),
    "load_next": ("Load next stack", "Chargez la pile suivante"),
    "scan": ("Scanning", "Numérisation"),
    "sheet": ("Scanning  /  sheet {n}, {side}", "Numérisation  /  feuille {n}, {side}"),
    "front": ("front", "recto"), "back": ("back", "verso"),
    "final": ("Finalizing", "Finalisation"), "busy": ("Scanner busy", "Scanner occupé"),
    "crop": ("Cropping", "Recadrage"), "filter": ("Checking blank sides", "Détection des blancs"),
    "check_text": ("Checking text", "Recherche de texte"), "orient": ("Rotating", "Orientation"),
    "clean": ("Cleaning", "Nettoyage"), "name": ("Reading title", "Nommage"),
    "verify_reference": ("Checking reference", "Contrôle des témoins"),
    "reference": ("Checking reference", "Contrôle des témoins"),
    "assemble": ("Creating PDF", "Création du PDF"), "process": ("Processing", "Traitement"),
    "side_count": ("side {n} of {t}", "face {n} sur {t}"), "pdf_count": ("PDF {n} of {t}", "PDF {n} sur {t}"),
    "queued_batches": ("Queued batches: {n}", "Lots en attente : {n}"),
    "queued": ("Queued for Paperless", "En attente de Paperless"), "sending": ("Sending to Paperless", "Envoi à Paperless"),
    "consuming": ("Paperless processing", "Import dans Paperless"), "verifying": ("Checking Inbox", "Vérification du tag Inbox"),
    "failed": ("Paperless delivery failed", "Échec de l'envoi à Paperless"),
    "uncertain": ("Check Paperless delivery", "Envoi à vérifier dans Paperless"),
    "proc_error": ("Processing failed", "Échec du traitement"), "scan_error": ("Check the feeder", "Vérifiez le chargeur"),
    "delivered": ("Paperless received  /  Inbox verified", "Reçu dans Paperless  /  Inbox vérifiée"),
    "pdf_ready": ("PDF ready", "PDF prêt"), "acquire": ("Acquiring originals", "Acquisition des originaux"),
    "idle": ("No pending tasks", "Aucune tâche en attente"),
    "offline": ("Controller offline", "Service déconnecté"), "retry": ("Reconnecting", "Reconnexion"),
    "rejected": ("Action unavailable", "Action indisponible"), "empty": ("Feeder is empty", "Chargeur vide"),
}

def message(lang, key, **values):
    return STRINGS[key][lang == "fr"].format(**values)
