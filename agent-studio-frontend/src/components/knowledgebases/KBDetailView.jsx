import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useWorkflow } from "@/context/WorkflowContext";
import {
  uploadDocument,
  listKBDocuments,
  deleteDocument,
  getKnowledgeBase,
  searchDocumentChunks,
  confirmStructuredSchema,
  getStructuredTablePreview,
  listRelationships,
  createRelationship,
  deleteRelationship,
  getKBAssets,
  updateStructuredColumnDescription,
} from "@/api/kb-client";
import Button from "../ui/Button";
import Input from "../ui/Input";
import Select from "../ui/Select";
import AlertModal from "../ui/AlertModal";
import ConfirmModal from "../ui/ConfirmModal";
import AppIcon from "../ui/AppIcon";
import { ApexSkeleton, ApexShellEmpty } from "../shell/ApexShellStates";
import {
  COLOR,
  FONT,
  KB_DETAIL,
  SEARCH,
  KB_MONO,
  KbRoseSpinner,
  KbDataTypeBadge,
  KbTab,
  KbPaginationFooter,
  KbDocSearchBar,
  KbSplitSeparator,
  KbCloseButton,
  KbTableSkeleton,
} from "./kbDetailUi";

export default function KBDetailView({ kbId, isShared = false, shareAccess: shareAccessProp = null }) {
  const { dispatch, ACTIONS } = useWorkflow();
  const [kb, setKb] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);

  // Per-document chunking config (shown before uploading non-structured files)
  const [chunkingModal, setChunkingModal] = useState(null);
  const [chunkingConfig, setChunkingConfig] = useState({
    chunking_method: "recursive",
    chunk_size: 1000,
    chunk_overlap: 0,
    delimiter: "",
  });

  // Vision processing config (used when chunking_method is 'vision')
  const [visionConfig, setVisionConfig] = useState({
    prompt: "",
    model: "vertex_ai.gemini-2.5-flash",
    output_schema_text: "",
  });

  // Per-document metadata inference
  const [inferMetadata, setInferMetadata] = useState(false);
  const [metadataFields, setMetadataFields] = useState([]);
  const [deletingDoc, setDeletingDoc] = useState(null);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [chunksData, setChunksData] = useState(null);
  const [chunksPage, setChunksPage] = useState(1);
  const [chunksSearch, setChunksSearch] = useState("");
  const [expandedChunkId, setExpandedChunkId] = useState(null);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [docSearch, setDocSearch] = useState("");
  const chunkSearchTimerRef = useRef(null);

  const filteredDocuments = useMemo(() => {
    const q = docSearch.trim().toLowerCase();
    if (!q) return documents;
    return documents.filter((d) => d.file_name?.toLowerCase().includes(q));
  }, [documents, docSearch]);
  const [hasProcessingDocs, setHasProcessingDocs] = useState(false);
  const [schemaModal, setSchemaModal] = useState(null);
  const [activeSheetTab, setActiveSheetTab] = useState(0);
  const [confirmingSchema, setConfirmingSchema] = useState(false);
  const [tablePreview, setTablePreview] = useState(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [previewPage, setPreviewPage] = useState(1);
  const [activePreviewTab, setActivePreviewTab] = useState(null);
  const [previewExpanded, setPreviewExpanded] = useState(false);

  const [showRelEditor, setShowRelEditor] = useState(false);
  const [relTables, setRelTables] = useState([]);
  const [relationships, setRelationships] = useState([]);
  const [relLoading, setRelLoading] = useState(false);
  const [relSaving, setRelSaving] = useState(false);
  const [relError, setRelError] = useState("");
  const [tablePositions, setTablePositions] = useState({});
  const [draggingTable, setDraggingTable] = useState(null);
  const [connecting, setConnecting] = useState(null);
  const [selectedRel, setSelectedRel] = useState(null);
  const [editRelModal, setEditRelModal] = useState(null);
  const [colTooltip, setColTooltip] = useState(null);
  const diagramRef = useRef(null);
  const dragOffsetRef = useRef({ x: 0, y: 0 });

  const [splitPosition, setSplitPosition] = useState(KB_DETAIL.splitDefault);
  const [isDraggingSplit, setIsDraggingSplit] = useState(false);
  const splitContainerRef = useRef(null);
  const isDraggingRef = useRef(false);

  // Column description popover (opens when the user clicks the "!" icon
  // on a column header in the structured-table preview).  Shape:
  //   { column: {...}, x: number, y: number }
  // Coordinates are viewport-relative so we render it as a fixed element.
  const [columnDescPopover, setColumnDescPopover] = useState(null);
  const [editingColumnDesc, setEditingColumnDesc] = useState(false);
  const [columnDescDraft, setColumnDescDraft] = useState("");
  const [savingColumnDesc, setSavingColumnDesc] = useState(false);

  // Polling ref for cleanup
  const pollingIntervalRef = useRef(null);

  useEffect(
    () => () => {
      if (chunkSearchTimerRef.current)
        clearTimeout(chunkSearchTimerRef.current);
    },
    [],
  );

  const loadChunks = useCallback(
    async (docId, page = 1, q = "") => {
      if (!kbId || !docId) return;
      setLoadingChunks(true);
      try {
        const data = await searchDocumentChunks(kbId, docId, {
          page,
          pageSize: KB_DETAIL.chunkPageSize,
          q,
        });
        setChunksData(data);
        setChunksPage(page);
        if (page === 1 && !q) setExpandedChunkId(null);
      } catch (error) {
        console.error("Failed to load chunks:", error);
        setAlertModal({
          isOpen: true,
          title: "Load Failed",
          message: `Failed to load chunks: ${error.message}`,
          variant: "error",
        });
      } finally {
        setLoadingChunks(false);
      }
    },
    [kbId],
  );

  // Modal state
  const [alertModal, setAlertModal] = useState({
    isOpen: false,
    title: "",
    message: "",
    variant: "error",
  });

  useEffect(() => {
    fetchKBDetails();
    fetchDocuments();

    // Cleanup polling on unmount or KB change
    return () => {
      stopPolling();
    };
  }, [kbId]);

  // Auto-select first document when documents load
  useEffect(() => {
    if (documents.length > 0 && !selectedDoc) {
      handleViewChunks(documents[0]);
    }
  }, [documents]);

  const fetchKBDetails = async () => {
    try {
      const data = await getKnowledgeBase(kbId);
      setKb(data);
    } catch (error) {
      console.error("Failed to load KB details:", error);
    }
  };

  // Prefer API share_access; fall back to navigation prop (not legacy isShared alone)
  const effectiveAccess = kb?.share_access ?? shareAccessProp ?? (isShared ? 'read' : 'owner');
  const isReadOnly = effectiveAccess === 'read';

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      const data = await listKBDocuments(kbId);
      setDocuments(data.documents || []);

      const processingDocs = (data.documents || []).filter(
        (doc) => doc.status === "processing",
      );

      if (processingDocs.length > 0) {
        setHasProcessingDocs(true);
        startDocumentPolling();
      } else {
        setHasProcessingDocs(false);
        stopPolling();
      }
    } catch (error) {
      console.error("Failed to load documents:", error);
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  };

  const startDocumentPolling = () => {
    stopPolling();

    pollingIntervalRef.current = setInterval(async () => {
      try {
        const data = await listKBDocuments(kbId);
        setDocuments(data.documents || []);

        const processingDocs = (data.documents || []).filter(
          (doc) => doc.status === "processing",
        );

        if (processingDocs.length === 0) {
          // All documents are in terminal state (completed/failed)
          setHasProcessingDocs(false);
          stopPolling();
          // Refresh KB details to update counts
          await fetchKBDetails();
        }
      } catch (error) {
        console.error("Failed to poll documents:", error);
      }
    }, 2000);
  };

  const stopPolling = () => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
  };

  const handleFileUpload = async (e) => {
    const files = Array.from(e.target.files);
    if (files.length === 0) return;

    const structuredExts = ["csv", "xlsx", "xls"];
    const firstExt = (files[0]?.name || "").split(".").pop()?.toLowerCase();
    const isStructured = structuredExts.includes(firstExt);

    if (isStructured) {
      // Structured files: upload immediately, then schema review
      setSchemaModal({ documentId: null, tables: null, loading: true });
      setActiveSheetTab(0);
      await doUploadFiles(files, true);
      e.target.value = "";
    } else {
      // Non-structured files: show chunking + metadata config modal first
      setChunkingModal({ files });
      setChunkingConfig({
        chunking_method: "recursive",
        chunk_size: 1000,
        chunk_overlap: 0,
        delimiter: "",
      });
      setVisionConfig({
        prompt: "",
        model: "vertex_ai.gemini-2.5-flash",
        output_schema_text: "",
      });
      setInferMetadata(false);
      setMetadataFields([]);
      e.target.value = "";
    }
  };

  const doUploadFiles = async (
    files,
    isStructured,
    chunkingOverrides = null,
    metaFields = null,
    visionCfg = null,
  ) => {
    setUploading(true);
    try {
      let schemaModalOpened = isStructured;
      for (const file of files) {
        const response = await uploadDocument(
          kbId,
          file,
          null,
          chunkingOverrides,
          metaFields,
          visionCfg,
        );
        if (
          response?.requires_schema_review &&
          response?.schema_preview?.tables
        ) {
          setSchemaModal({
            documentId: response.document_id,
            tables: response.schema_preview.tables,
            existingNames: response.schema_preview.existing_table_names || [],
            loading: false,
          });
          setActiveSheetTab(0);
        }
      }
      if (!schemaModalOpened) await fetchDocuments();
    } catch (error) {
      console.error("Failed to upload files:", error);
      setSchemaModal(null);
      setAlertModal({
        isOpen: true,
        title: "Upload Failed",
        message: error.message,
        variant: "error",
      });
    } finally {
      setUploading(false);
    }
  };

  const handleChunkingConfirm = async () => {
    if (!chunkingModal?.files) return;

    const isVision = chunkingConfig.chunking_method === "vision";
    const files = chunkingModal.files;
    setChunkingModal(null);

    if (isVision) {
      let parsedSchema = null;
      if (visionConfig.output_schema_text?.trim()) {
        try {
          parsedSchema = JSON.parse(visionConfig.output_schema_text);
        } catch {
          /* ignore invalid JSON */
        }
      }
      const vc = {
        prompt: visionConfig.prompt,
        model: visionConfig.model || "vertex_ai.gemini-2.5-flash",
        output_schema: parsedSchema,
      };
      await doUploadFiles(files, false, null, null, vc);
    } else {
      const overrides = {
        chunking_method: chunkingConfig.chunking_method,
        chunk_size: parseInt(chunkingConfig.chunk_size) || 1000,
        chunk_overlap: parseInt(chunkingConfig.chunk_overlap) || 0,
        delimiter:
          chunkingConfig.chunking_method === "delimiter"
            ? chunkingConfig.delimiter
            : undefined,
      };
      const metaFields =
        inferMetadata && metadataFields.length > 0
          ? metadataFields
              .filter((f) => f.name.trim())
              .map((f) => ({
                name: f.name.trim(),
                type: f.type,
                scope: f.scope,
                description: f.description?.trim() || undefined,
              }))
          : null;
      await doUploadFiles(files, false, overrides, metaFields);
    }
  };

  const handleDeleteDoc = async () => {
    if (!deletingDoc) return;

    try {
      const wasSelected = selectedDoc?.id === deletingDoc.id;
      await deleteDocument(deletingDoc.id, false);
      if (wasSelected) {
        setSelectedDoc(null);
        setTablePreview(null);
        setChunksData(null);
        setChunksSearch("");
      }
      await fetchDocuments();
      await fetchKBDetails();
      setDeletingDoc(null);
    } catch (error) {
      console.error("Failed to delete document:", error);
      setAlertModal({
        isOpen: true,
        title: "Deletion Failed",
        message: `Failed to delete: ${error.message}`,
        variant: "error",
      });
    }
  };

  const sanitizeTableName = (name) => {
    if (!name) return "";
    let s = name
      .replace(/\.[^.]+$/, "")
      .replace(/[^a-zA-Z0-9_]/g, "_")
      .toLowerCase();
    s = s.replace(/_+/g, "_").replace(/^_|_$/g, "").slice(0, 63);
    if (s && /^\d/.test(s)) s = "t_" + s;
    return s;
  };

  const getTableNameConflict = (tableIdx) => {
    if (!schemaModal?.tables) return null;
    const table = schemaModal.tables[tableIdx];
    const sanitized = sanitizeTableName(table?.table_name || "");
    if (!sanitized) return "Table name is required";
    const existingSet = new Set(
      (schemaModal.existingNames || []).map((n) => n.toLowerCase()),
    );
    if (existingSet.has(sanitized))
      return `Table "${sanitized}" already exists in this KB`;
    for (let i = 0; i < schemaModal.tables.length; i++) {
      if (
        i !== tableIdx &&
        sanitizeTableName(schemaModal.tables[i]?.table_name) === sanitized
      ) {
        return `Duplicate name with another table in this upload`;
      }
    }
    return null;
  };

  const hasAnyTableConflict = () => {
    if (!schemaModal?.tables) return false;
    return schemaModal.tables.some((_, i) => getTableNameConflict(i));
  };

  const handleConfirmSchema = async () => {
    if (!schemaModal) return;
    if (hasAnyTableConflict()) {
      setAlertModal({
        isOpen: true,
        title: "Table Name Conflict",
        message:
          "One or more table names conflict with existing tables. Please rename them.",
        variant: "error",
      });
      return;
    }
    try {
      setConfirmingSchema(true);
      const tablesToSend = schemaModal.tables.map((t) => ({
        table_name: t.table_name,
        sheet_name: t.sheet_name,
        description: t.table_description,
        display_name: t.table_name,
        columns: (t.columns || []).map((c) => ({
          column_name: c.column_name,
          display_name: c.display_name || c.column_name,
          data_type: c.data_type,
          description: c.description,
          nullable: c.nullable !== false,
        })),
      }));
      const result = await confirmStructuredSchema(
        schemaModal.documentId,
        tablesToSend,
      );
      setSchemaModal(null);
      await fetchDocuments();
      await fetchKBDetails();
      if (result?.warnings?.length > 0) {
        setAlertModal({
          isOpen: true,
          title: "Data Loaded with Warnings",
          message: result.warnings.join("\n\n"),
          variant: "warning",
        });
      }
    } catch (error) {
      setAlertModal({
        isOpen: true,
        title: "Schema Error",
        message: error.message,
        variant: "error",
      });
    } finally {
      setConfirmingSchema(false);
    }
  };

  const updateSchemaTable = (tableIdx, field, value) => {
    setSchemaModal((prev) => {
      const tables = [...prev.tables];
      tables[tableIdx] = { ...tables[tableIdx], [field]: value };
      return { ...prev, tables };
    });
  };

  const updateSchemaColumn = (tableIdx, colIdx, field, value) => {
    setSchemaModal((prev) => {
      const tables = [...prev.tables];
      const columns = [...tables[tableIdx].columns];
      columns[colIdx] = { ...columns[colIdx], [field]: value };
      tables[tableIdx] = { ...tables[tableIdx], columns };
      return { ...prev, tables };
    });
  };

  const removeSchemaTable = (idx) => {
    const currentLen = schemaModal?.tables?.length || 0;
    if (currentLen <= 1) return;

    setSchemaModal((prev) => ({
      ...prev,
      tables: prev.tables.filter((_, i) => i !== idx),
    }));

    setActiveSheetTab((curr) => {
      if (curr > idx) return curr - 1;
      if (curr === idx) return Math.min(idx, currentLen - 2);
      return curr;
    });
  };

  const handleCancelSchema = async () => {
    const docId = schemaModal?.documentId;
    setSchemaModal(null);

    if (docId) {
      try {
        await deleteDocument(docId, false);
        await fetchDocuments();
        await fetchKBDetails();
      } catch (error) {
        console.error("Failed to clean up cancelled document:", error);
      }
    }
  };

  const handlePreviewPageChange = async (newPage) => {
    if (!selectedDoc) return;
    setLoadingPreview(true);
    setPreviewPage(newPage);
    try {
      const result = await getStructuredTablePreview(selectedDoc.id, {
        page: newPage,
        sheetTableId: activePreviewTab,
      });
      setTablePreview(result);
    } catch (error) {
      setAlertModal({
        isOpen: true,
        title: "Load Failed",
        message: error.message,
        variant: "error",
      });
    } finally {
      setLoadingPreview(false);
    }
  };

  const handlePreviewTabChange = async (tableId) => {
    if (!selectedDoc) return;
    setActivePreviewTab(tableId);
    setPreviewPage(1);
    setLoadingPreview(true);
    try {
      const result = await getStructuredTablePreview(selectedDoc.id, {
        page: 1,
        sheetTableId: tableId,
      });
      setTablePreview(result);
    } catch (error) {
      setAlertModal({
        isOpen: true,
        title: "Load Failed",
        message: error.message,
        variant: "error",
      });
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleViewChunks = async (doc) => {
    try {
      setSelectedDoc(doc);
      setTablePreview(null);
      setChunksData(null);
      setChunksSearch("");
      setChunksPage(1);
      setExpandedChunkId(null);
      setActivePreviewTab(null);
      if (doc.is_structured) {
        setLoadingPreview(true);
        setPreviewPage(1);
        const result = await getStructuredTablePreview(doc.id);
        setTablePreview(result);
        if (result?.tables?.length > 0) {
          setActivePreviewTab(result.tables[0].id);
        }
      } else {
        await loadChunks(doc.id, 1, "");
      }
    } catch (error) {
      console.error("Failed to load:", error);
      setAlertModal({
        isOpen: true,
        title: "Load Failed",
        message: `Failed to load: ${error.message}`,
        variant: "error",
      });
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleChunksSearchChange = (value) => {
    setChunksSearch(value);
    if (!selectedDoc?.id) return;
    if (chunkSearchTimerRef.current) clearTimeout(chunkSearchTimerRef.current);
    chunkSearchTimerRef.current = setTimeout(() => {
      loadChunks(selectedDoc.id, 1, value);
    }, 400);
  };

  const formatSize = (bytes) => {
    if (!bytes) return "0 B";
    const mb = bytes / (1024 * 1024);
    if (mb < 1) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${mb.toFixed(1)} MB`;
  };

  const formatStatus = (status) => {
    const statusMap = {
      pending: { label: "Pending", bg: COLOR.warningBg, fg: COLOR.warningFg },
      schema_review: {
        label: "Schema review",
        bg: COLOR.warningBg,
        fg: COLOR.warningFg,
      },
      processing: {
        label: "Processing",
        bg: "rgba(22, 106, 197, 0.15)",
        fg: "#7eb8ff",
      },
      completed: {
        label: "Completed",
        bg: COLOR.successBg,
        fg: COLOR.successFg,
      },
      failed: { label: "Failed", bg: COLOR.errorBg, fg: COLOR.errorFg },
    };
    const s = statusMap[status] || statusMap.pending;
    return (
      <span
        className="inline-flex items-center gap-1 text-xs font-semibold"
        style={{
          padding: "2px 8px",
          borderRadius: 6,
          backgroundColor: s.bg,
          color: s.fg,
          fontFamily: FONT.family,
        }}
      >
        {status === "processing" && (
          <span
            className="inline-block rounded-full animate-spin"
            style={{
              width: 10,
              height: 10,
              border: `2px solid ${s.fg}`,
              borderTopColor: "transparent",
            }}
          />
        )}
        {s.label}
      </span>
    );
  };

  const kbActionButtonStyle = {
    borderRadius: KB_DETAIL.buttonRadius,
    fontFamily: FONT.family,
    fontSize: FONT.body3.size,
    fontWeight: FONT.pillButton.weight,
  };

  const TABLE_CARD_W = 220;
  const COL_ROW_H = 26;
  const TABLE_HEADER_H = 36;

  const autoLayoutTables = useCallback((tables) => {
    const cols = Math.max(2, Math.ceil(Math.sqrt(tables.length)));
    const gapX = 300,
      gapY = 60;
    const positions = {};
    tables.forEach((t, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const cardH = TABLE_HEADER_H + (t.columns?.length || 1) * COL_ROW_H + 8;
      positions[t.id] = { x: 40 + col * gapX, y: 40 + row * (cardH + gapY) };
    });
    return positions;
  }, []);

  const openRelEditor = async () => {
    setShowRelEditor(true);
    setRelLoading(true);
    setRelError("");
    setSelectedRel(null);
    setConnecting(null);
    setEditRelModal(null);
    try {
      const [assets, rels] = await Promise.all([
        getKBAssets(kbId),
        listRelationships(kbId),
      ]);
      const tables = assets?.structured_tables || [];
      setRelTables(tables);
      setRelationships(rels || []);
      setTablePositions(autoLayoutTables(tables));
    } catch (err) {
      console.error("Failed to load relationship data:", err);
    } finally {
      setRelLoading(false);
    }
  };

  const handleSaveRelationship = async (
    srcTableId,
    srcColId,
    tgtTableId,
    tgtColId,
    relType = "one_to_many",
  ) => {
    setRelError("");
    if (srcTableId === tgtTableId) {
      setRelError("Source and target must be different tables.");
      return;
    }
    setRelSaving(true);
    try {
      await createRelationship(kbId, {
        source_table_id: srcTableId,
        source_column_id: srcColId,
        target_table_id: tgtTableId,
        target_column_id: tgtColId,
        relationship_type: relType,
      });
      const rels = await listRelationships(kbId);
      setRelationships(rels || []);
    } catch (err) {
      setRelError(err.message || "Failed to create relationship");
    } finally {
      setRelSaving(false);
    }
  };

  const handleDeleteRelationship = async (relId) => {
    try {
      await deleteRelationship(kbId, relId);
      setRelationships((prev) => prev.filter((r) => r.id !== relId));
      setSelectedRel(null);
      setEditRelModal(null);
    } catch (err) {
      setRelError(err.message || "Failed to delete relationship");
    }
  };

  const handleUpdateRelType = async (relId, newType) => {
    setRelSaving(true);
    try {
      await deleteRelationship(kbId, relId);
      const rel = relationships.find((r) => r.id === relId);
      if (rel) {
        const srcTable = relTables.find(
          (t) => t.table_name === rel.source_table_name,
        );
        const tgtTable = relTables.find(
          (t) => t.table_name === rel.target_table_name,
        );
        const srcCol = (srcTable?.columns || []).find(
          (c) => c.column_name === rel.source_column_name,
        );
        const tgtCol = (tgtTable?.columns || []).find(
          (c) => c.column_name === rel.target_column_name,
        );
        if (srcTable && tgtTable && srcCol && tgtCol) {
          await createRelationship(kbId, {
            source_table_id: srcTable.id,
            source_column_id: srcCol.id,
            target_table_id: tgtTable.id,
            target_column_id: tgtCol.id,
            relationship_type: newType,
          });
        }
      }
      const rels = await listRelationships(kbId);
      setRelationships(rels || []);
      setEditRelModal(null);
      setSelectedRel(null);
    } catch (err) {
      setRelError(err.message || "Failed to update relationship");
    } finally {
      setRelSaving(false);
    }
  };

  const getColumnAnchor = useCallback(
    (tableId, columnId, side) => {
      const pos = tablePositions[tableId];
      if (!pos) return { x: 0, y: 0 };
      const table = relTables.find((t) => t.id === tableId);
      if (!table) return { x: pos.x, y: pos.y };
      const colIdx = (table.columns || []).findIndex(
        (c) => c.id === columnId || c.column_name === columnId,
      );
      const y =
        pos.y +
        TABLE_HEADER_H +
        (colIdx >= 0 ? colIdx : 0) * COL_ROW_H +
        COL_ROW_H / 2;
      const x = side === "right" ? pos.x + TABLE_CARD_W : pos.x;
      return { x, y };
    },
    [tablePositions, relTables],
  );

  const getRelLine = useCallback(
    (rel) => {
      const srcTable = relTables.find(
        (t) => t.table_name === rel.source_table_name,
      );
      const tgtTable = relTables.find(
        (t) => t.table_name === rel.target_table_name,
      );
      if (!srcTable || !tgtTable) return null;
      const srcCol = (srcTable.columns || []).find(
        (c) => c.column_name === rel.source_column_name,
      );
      const tgtCol = (tgtTable.columns || []).find(
        (c) => c.column_name === rel.target_column_name,
      );
      if (!srcCol || !tgtCol) return null;
      const srcPos = tablePositions[srcTable.id];
      const tgtPos = tablePositions[tgtTable.id];
      if (!srcPos || !tgtPos) return null;
      const srcRight = srcPos.x + TABLE_CARD_W;
      const tgtLeft = tgtPos.x;
      const srcSide =
        srcRight <= tgtLeft
          ? "right"
          : srcPos.x >= tgtPos.x + TABLE_CARD_W
            ? "left"
            : srcPos.x < tgtPos.x
              ? "right"
              : "left";
      const tgtSide = srcSide === "right" ? "left" : "right";
      const from = getColumnAnchor(srcTable.id, srcCol.column_name, srcSide);
      const to = getColumnAnchor(tgtTable.id, tgtCol.column_name, tgtSide);
      return { from, to, srcSide, tgtSide };
    },
    [relTables, tablePositions, getColumnAnchor],
  );

  const onTableMouseDown = useCallback(
    (e, tableId) => {
      if (e.target.closest("[data-col-handle]")) return;
      e.preventDefault();
      const rect = diagramRef.current?.getBoundingClientRect();
      if (!rect) return;
      const pos = tablePositions[tableId] || { x: 0, y: 0 };
      dragOffsetRef.current = {
        x: e.clientX - rect.left - pos.x,
        y: e.clientY - rect.top - pos.y,
      };
      setDraggingTable(tableId);
    },
    [tablePositions],
  );

  useEffect(() => {
    if (!draggingTable) return;
    const handleMove = (e) => {
      const rect = diagramRef.current?.getBoundingClientRect();
      if (!rect) return;
      const x = e.clientX - rect.left - dragOffsetRef.current.x;
      const y = e.clientY - rect.top - dragOffsetRef.current.y;
      setTablePositions((prev) => ({
        ...prev,
        [draggingTable]: { x: Math.max(0, x), y: Math.max(0, y) },
      }));
    };
    const handleUp = () => setDraggingTable(null);
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
  }, [draggingTable]);

  const onColHandleMouseDown = useCallback((e, tableId, colId) => {
    e.preventDefault();
    e.stopPropagation();
    const rect = diagramRef.current?.getBoundingClientRect();
    if (!rect) return;
    setConnecting({
      sourceTableId: tableId,
      sourceColumnId: colId,
      mouseX: e.clientX - rect.left,
      mouseY: e.clientY - rect.top,
    });
  }, []);

  useEffect(() => {
    if (!connecting) return;
    const handleMove = (e) => {
      const rect = diagramRef.current?.getBoundingClientRect();
      if (!rect) return;
      setConnecting((prev) =>
        prev
          ? {
              ...prev,
              mouseX: e.clientX - rect.left,
              mouseY: e.clientY - rect.top,
            }
          : null,
      );
    };
    const handleUp = (e) => {
      const el = document.elementFromPoint(e.clientX, e.clientY);
      const handle = el?.closest("[data-col-handle]");
      if (handle) {
        const tgtTableId = handle.getAttribute("data-table-id");
        const tgtColId = handle.getAttribute("data-col-id");
        if (tgtTableId && tgtColId && tgtTableId !== connecting.sourceTableId) {
          handleSaveRelationship(
            connecting.sourceTableId,
            connecting.sourceColumnId,
            tgtTableId,
            tgtColId,
          );
        }
      }
      setConnecting(null);
    };
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
  }, [connecting]);

  const hasStructuredDocs = documents.some((d) => d.is_structured);

  const handleSeparatorMouseDown = useCallback((e) => {
    e.preventDefault();
    isDraggingRef.current = true;
    setIsDraggingSplit(true);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const handleMouseMove = (moveEvent) => {
      if (!isDraggingRef.current || !splitContainerRef.current) return;
      const rect = splitContainerRef.current.getBoundingClientRect();
      const x = moveEvent.clientX - rect.left;
      const percentage = (x / rect.width) * 100;
      setSplitPosition(Math.min(72, Math.max(28, percentage)));
    };

    const handleMouseUp = () => {
      isDraggingRef.current = false;
      setIsDraggingSplit(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  }, []);

  const handleSeparatorDoubleClick = useCallback(() => {
    setSplitPosition(KB_DETAIL.splitDefault);
  }, []);

  const openColumnDescPopover = useCallback((e, col) => {
    e.stopPropagation();
    const rect = e.currentTarget.getBoundingClientRect();
    const POP_W = 300;
    // Anchor the popover below the icon, clamped to the viewport so it
    // never overflows on the right edge of the expanded table view.
    const x = Math.min(
      Math.max(8, rect.left),
      (typeof window !== "undefined" ? window.innerWidth : 1200) - POP_W - 8,
    );
    setColumnDescPopover({ column: col, x, y: rect.bottom + 6 });
    setEditingColumnDesc(false);
    setColumnDescDraft(col.description || "");
  }, []);

  const closeColumnDescPopover = useCallback(() => {
    setColumnDescPopover(null);
    setEditingColumnDesc(false);
    setColumnDescDraft("");
    setSavingColumnDesc(false);
  }, []);

  const handleSaveColumnDescription = useCallback(async () => {
    if (!columnDescPopover?.column?.id) return;
    const columnId = columnDescPopover.column.id;
    setSavingColumnDesc(true);
    try {
      const updated = await updateStructuredColumnDescription(
        kbId,
        columnId,
        columnDescDraft,
      );
      const newDesc = updated?.description || "";
      // Patch the description in place so all table header icons reflect
      // the new value without refetching the preview.
      setTablePreview((prev) => {
        if (!prev) return prev;
        const patchCols = (cols) =>
          (cols || []).map((c) =>
            c.id === columnId ? { ...c, description: newDesc } : c,
          );
        const newTable = prev.table
          ? { ...prev.table, columns: patchCols(prev.table.columns) }
          : prev.table;
        const newTables = (prev.tables || []).map((t) => ({
          ...t,
          columns: patchCols(t.columns),
        }));
        return { ...prev, table: newTable, tables: newTables };
      });
      setColumnDescPopover((prev) =>
        prev
          ? { ...prev, column: { ...prev.column, description: newDesc } }
          : prev,
      );
      setEditingColumnDesc(false);
    } catch (err) {
      setAlertModal({
        isOpen: true,
        title: "Update Failed",
        message: `Failed to update column description: ${err.message}`,
        variant: "error",
      });
    } finally {
      setSavingColumnDesc(false);
    }
  }, [columnDescPopover, columnDescDraft, kbId]);

  const chunkList = chunksData?.chunks || [];
  const chunkTotal = chunksData?.total ?? selectedDoc?.chunk_count ?? 0;
  const chunkTotalPages = chunksData?.total_pages ?? 1;

  return (
    <div
      data-theme="apex-dark"
      className="h-full w-full flex flex-col overflow-hidden"
      style={{ backgroundColor: COLOR.black, fontFamily: FONT.family }}
    >
      {/* Header */}
      <div
        style={{
          borderBottom: `1px solid ${COLOR.darker}`,
          backgroundColor: COLOR.darkest,
          flexShrink: 0,
        }}
      >
        <div style={{ padding: "24px" }}>
          <div
            className="flex items-center justify-between"
            style={{ marginBottom: 20 }}
          >
            <div className="flex items-center" style={{ gap: 16 }}>
              <button
                type="button"
                onClick={() => dispatch({ type: ACTIONS.NAVIGATE_BACK })}
                title="Back"
                style={{
                  padding: 8,
                  borderRadius: KB_DETAIL.buttonRadius,
                  border: "none",
                  backgroundColor: "transparent",
                  color: COLOR.light,
                  cursor: "pointer",
                  transition: "background-color 150ms",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor =
                    "rgba(255,255,255,0.06)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = "transparent";
                }}
              >
                <AppIcon name="back" size={20} color={COLOR.light} />
              </button>
              <div>
                <h1
                  style={{
                    margin: 0,
                    color: COLOR.white,
                    fontSize: FONT.sub2Bold.size,
                    lineHeight: `${FONT.sub2Bold.height}px`,
                    fontWeight: FONT.sub2Bold.weight,
                  }}
                >
                  {kb?.name || "Knowledge Base"}
                </h1>
                <p
                  style={{
                    margin: "4px 0 0",
                    color: COLOR.medium,
                    fontSize: FONT.body3.size,
                    lineHeight: `${FONT.body3.height}px`,
                  }}
                >
                  {kb?.description || "Manage documents and search settings"}
                </p>
              </div>
            </div>
            <div className="flex items-center" style={{ gap: 12 }}>
              {effectiveAccess === 'read' && (
                <span
                  style={{
                    padding: "4px 12px",
                    fontSize: 12,
                    fontWeight: 600,
                    borderRadius: 6,
                    backgroundColor: "rgba(22, 106, 197, 0.15)",
                    color: "#7eb8ff",
                  }}
                >
                  Shared (read-only)
                </span>
              )}
              {effectiveAccess === 'write' && (
                <span
                  style={{
                    padding: "4px 12px",
                    fontSize: 12,
                    fontWeight: 600,
                    borderRadius: 6,
                    backgroundColor: "rgba(34, 197, 94, 0.15)",
                    color: "#86efac",
                  }}
                >
                  Shared (read &amp; write)
                </span>
              )}
              {!isReadOnly && (
                <>
                  <input
                    type="file"
                    id="file-upload"
                    multiple
                    accept=".pdf,.txt,.xml,.json,.csv,.md,.docx,.doc,.html,.htm,.rtf,.xlsx,.pptx"
                    onChange={handleFileUpload}
                    className="hidden"
                  />
                  {hasStructuredDocs && (
                    <Button
                      variant="outline"
                      onClick={openRelEditor}
                      className="flex items-center gap-2"
                      style={kbActionButtonStyle}
                    >
                      <AppIcon name="share" size={16} color={COLOR.medium} />
                      <span>Manage relationships</span>
                    </Button>
                  )}
                  <Button
                    onClick={() =>
                      document.getElementById("file-upload").click()
                    }
                    disabled={uploading}
                    className="flex items-center gap-2"
                    style={{
                      ...kbActionButtonStyle,
                      backgroundColor: COLOR.rose,
                      color: COLOR.white,
                    }}
                  >
                    {uploading ? (
                      <>
                        <span
                          className="inline-block rounded-full animate-spin"
                          style={{
                            width: 16,
                            height: 16,
                            border: "2px solid white",
                            borderTopColor: "transparent",
                          }}
                        />
                        <span>Uploading…</span>
                      </>
                    ) : (
                      <>
                        <AppIcon
                          name="upload"
                          size={18}
                          color={COLOR.white}
                          weight="bold"
                        />
                        <span>Upload documents</span>
                      </>
                    )}
                  </Button>
                </>
              )}
            </div>
          </div>

          {kb && (
            <div className="grid grid-cols-4" style={{ gap: 12 }}>
              {[
                {
                  label: "Documents",
                  value: kb.document_count || 0,
                  highlight: false,
                },
                {
                  label: "Chunks",
                  value: kb.chunk_count || 0,
                  highlight: true,
                },
                {
                  label: "Size",
                  value: formatSize(kb.total_size_bytes),
                  highlight: false,
                },
                {
                  label: "Embedding",
                  value: (kb.embedding_model || "").replace(
                    /^azure_/,
                    "Azure ",
                  ),
                  sub: `${kb.vector_dimension}D`,
                  highlight: false,
                },
              ].map((stat) => (
                <div
                  key={stat.label}
                  style={{
                    backgroundColor: stat.highlight
                      ? "rgba(217, 56, 84, 0.08)"
                      : COLOR.black,
                    border: `1px solid ${stat.highlight ? "rgba(217, 56, 84, 0.25)" : COLOR.darker}`,
                    borderRadius: KB_DETAIL.statRadius,
                    padding: 16,
                  }}
                >
                  <div
                    style={{
                      fontSize: FONT.body3.size,
                      color: COLOR.medium,
                      marginBottom: 4,
                    }}
                  >
                    {stat.label}
                  </div>
                  <div
                    style={{
                      fontSize: FONT.body1Bold.size,
                      fontWeight: FONT.body1Bold.weight,
                      color: COLOR.white,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {stat.value}
                  </div>
                  {stat.sub && (
                    <div
                      style={{ fontSize: 12, color: COLOR.dark, marginTop: 2 }}
                    >
                      {stat.sub}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Split View: Documents List + Chunks Panel */}
      <div
        ref={splitContainerRef}
        className="flex flex-1 min-h-0 overflow-hidden"
      >
        {/* Documents List - Left Side */}
        <div
          style={{ width: `${splitPosition}%` }}
          className="flex-shrink-0 pl-6 pr-4 py-8 overflow-y-auto min-w-0"
        >
          {documents.length > 3 && !loading && (
            <KbDocSearchBar value={docSearch} onChange={setDocSearch} />
          )}
          {loading ? (
            <div style={{ padding: 8 }}>
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  style={{
                    marginBottom: 12,
                    padding: 16,
                    borderRadius: KB_DETAIL.cardRadius,
                    backgroundColor: COLOR.darkest,
                    border: `1px solid ${COLOR.darker}`,
                  }}
                >
                  <ApexSkeleton
                    width="70%"
                    height={16}
                    style={{ marginBottom: 10 }}
                  />
                  <ApexSkeleton width="45%" height={12} />
                </div>
              ))}
            </div>
          ) : documents.length === 0 ? (
            <ApexShellEmpty
              title="No documents yet"
              description={
                isReadOnly
                  ? "This shared knowledge base has no documents."
                  : "Upload documents to start building your knowledge base."
              }
              style={{ marginTop: 48 }}
            />
          ) : (
            <div className="space-y-3">
              {filteredDocuments.length === 0 && documents.length > 0 && (
                <p
                  style={{
                    fontSize: FONT.body3.size,
                    color: COLOR.medium,
                    textAlign: "center",
                    padding: 16,
                  }}
                >
                  No documents match your search.
                </p>
              )}
              {filteredDocuments.map((doc) => {
                const isSelected = selectedDoc?.id === doc.id;
                const isStructured =
                  doc.is_structured ||
                  ["csv", "xlsx", "xls"].includes(
                    (doc.file_type || "").toLowerCase(),
                  );
                return (
                  <div
                    key={doc.id}
                    onClick={() => handleViewChunks(doc)}
                    className="transition-all cursor-pointer"
                    style={{
                      backgroundColor: isSelected
                        ? "rgba(217, 56, 84, 0.06)"
                        : COLOR.darkest,
                      borderRadius: KB_DETAIL.cardRadius,
                      border: `1px solid ${isSelected ? COLOR.rose : COLOR.darker}`,
                      borderLeftWidth: isSelected ? 3 : 1,
                      borderLeftColor: isSelected ? COLOR.rose : COLOR.darker,
                      padding: 16,
                    }}
                    onMouseEnter={(e) => {
                      if (!isSelected)
                        e.currentTarget.style.borderColor = COLOR.dark;
                    }}
                    onMouseLeave={(e) => {
                      if (!isSelected)
                        e.currentTarget.style.borderColor = COLOR.darker;
                    }}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-3 mb-2">
                          <div
                            className="flex-shrink-0 flex items-center justify-center"
                            style={{
                              width: 36,
                              height: 36,
                              borderRadius: 8,
                              backgroundColor: "rgba(255,255,255,0.04)",
                            }}
                          >
                            <AppIcon
                              name={
                                isStructured ? "excel-generator" : "fileDoc"
                              }
                              size={22}
                              color={isSelected ? COLOR.rose : COLOR.medium}
                            />
                          </div>
                          <div className="flex-1 min-w-0">
                            <h4
                              className="truncate"
                              style={{
                                margin: 0,
                                color: COLOR.white,
                                fontSize: FONT.body2.size,
                                fontWeight: FONT.body2Bold.weight,
                              }}
                              title={doc.file_name}
                            >
                              {doc.file_name}
                            </h4>
                            <div
                              className="flex flex-wrap items-center gap-x-3 gap-y-1"
                              style={{
                                marginTop: 4,
                                fontSize: 12,
                                color: COLOR.medium,
                              }}
                            >
                              <span>{formatSize(doc.file_size)}</span>
                              <span>{doc.file_type?.toUpperCase()}</span>
                              <span>{doc.chunk_count || 0} chunks</span>
                              <span>
                                {new Date(doc.created_at).toLocaleDateString()}
                              </span>
                            </div>
                          </div>
                        </div>
                        <div style={{ marginLeft: 48 }}>
                          {formatStatus(doc.status)}
                          {doc.embedding_status && (
                            <span
                              style={{
                                marginLeft: 8,
                                fontSize: 12,
                                color: COLOR.dark,
                              }}
                            >
                              Embedding: {doc.embedding_status}
                            </span>
                          )}
                        </div>
                      </div>
                      {!isReadOnly && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeletingDoc(doc);
                          }}
                          title="Delete document"
                          style={{
                            flexShrink: 0,
                            marginLeft: 8,
                            padding: 8,
                            border: "none",
                            borderRadius: KB_DETAIL.buttonRadius,
                            backgroundColor: "transparent",
                            color: COLOR.errorFg,
                            cursor: "pointer",
                            transition: "background-color 150ms",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.backgroundColor =
                              COLOR.errorBg;
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.backgroundColor =
                              "transparent";
                          }}
                        >
                          <AppIcon
                            name="trash"
                            size={16}
                            color="currentColor"
                          />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Draggable Separator */}
        {!previewExpanded && (
          <KbSplitSeparator
            isDragging={isDraggingSplit}
            onMouseDown={handleSeparatorMouseDown}
            onDoubleClick={handleSeparatorDoubleClick}
          />
        )}

        {isDraggingSplit && (
          <div className="fixed inset-0 z-50 cursor-col-resize" />
        )}

        {/* Chunks / Table Preview Panel - Right Side */}
        {!previewExpanded && (
          <div
            style={{
              width: `${100 - splitPosition}%`,
              backgroundColor: COLOR.black,
            }}
            className="flex-shrink-0 flex flex-col min-w-0"
          >
            {selectedDoc ? (
              <>
                <div
                  className="flex flex-col flex-shrink-0"
                  style={{
                    padding: "16px 24px",
                    borderBottom: `1px solid ${COLOR.darker}`,
                    backgroundColor: COLOR.darkest,
                    gap: 12,
                  }}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <h3
                        style={{
                          margin: 0,
                          color: COLOR.white,
                          fontSize: FONT.body1Bold.size,
                          fontWeight: FONT.body1Bold.weight,
                        }}
                      >
                        {selectedDoc?.is_structured
                          ? "Table data"
                          : "Document chunks"}
                      </h3>
                      <p
                        className="truncate"
                        style={{
                          margin: "4px 0 0",
                          color: COLOR.medium,
                          fontSize: FONT.body3.size,
                        }}
                        title={selectedDoc.file_name}
                      >
                        {selectedDoc.file_name}
                        {!selectedDoc?.is_structured && (
                          <span style={{ color: COLOR.dark }}>
                            {" "}
                            · {chunkTotal} chunks
                          </span>
                        )}
                      </p>
                    </div>
                    {selectedDoc?.is_structured && tablePreview && (
                      <button
                        type="button"
                        onClick={() => setPreviewExpanded(true)}
                        title="Expand table view"
                        className="flex items-center flex-shrink-0"
                        style={{
                          gap: 6,
                          padding: "6px 12px",
                          fontSize: 12,
                          fontWeight: 600,
                          color: COLOR.light,
                          backgroundColor: "rgba(255,255,255,0.06)",
                          border: `1px solid ${COLOR.darker}`,
                          borderRadius: KB_DETAIL.buttonRadius,
                          cursor: "pointer",
                          fontFamily: FONT.family,
                        }}
                      >
                        <AppIcon
                          name="fitScreen"
                          size={16}
                          color={COLOR.light}
                        />
                        Expand
                      </button>
                    )}
                  </div>
                  {!selectedDoc?.is_structured && (
                    <div
                      className="kb-inline-search flex items-center"
                      style={{
                        height: SEARCH.height,
                        borderRadius: SEARCH.radius,
                        paddingLeft: SEARCH.paddingX,
                        paddingRight: SEARCH.paddingX,
                        gap: SEARCH.gap,
                        backgroundColor: COLOR.black,
                        border: `1px solid ${COLOR.darker}`,
                      }}
                    >
                      <AppIcon
                        name="search"
                        size={SEARCH.iconSize}
                        color={SEARCH.iconColor}
                      />
                      <input
                        type="text"
                        className="force-white-text"
                        placeholder="Search chunks"
                        value={chunksSearch}
                        onChange={(e) =>
                          handleChunksSearchChange(e.target.value)
                        }
                        style={{
                          flex: 1,
                          minWidth: 0,
                          border: "none",
                          outline: "none",
                          backgroundColor: "transparent",
                          color: COLOR.white,
                          fontFamily: FONT.family,
                          fontSize: FONT.body2.size,
                        }}
                      />
                    </div>
                  )}
                </div>
                {selectedDoc?.is_structured ? (
                  <>
                    {loadingPreview && !tablePreview ? (
                      <div className="flex items-center justify-center flex-1">
                        <KbRoseSpinner size={40} />
                      </div>
                    ) : tablePreview ? (
                      <div className="flex-1 flex flex-col overflow-hidden min-h-0">
                        {(tablePreview.tables || []).length > 1 && (
                          <div
                            className="flex flex-wrap flex-shrink-0"
                            style={{
                              padding: "8px 16px 0",
                              gap: 4,
                              backgroundColor: COLOR.black,
                              borderBottom: `1px solid ${COLOR.darker}`,
                            }}
                          >
                            {tablePreview.tables.map((t) => (
                              <KbTab
                                key={t.id}
                                active={
                                  (activePreviewTab ||
                                    tablePreview.tables[0]?.id) === t.id
                                }
                                onClick={() => handlePreviewTabChange(t.id)}
                                count={t.row_count ?? "?"}
                              >
                                {t.display_name ||
                                  t.table_name ||
                                  t.source_sheet ||
                                  "Table"}
                              </KbTab>
                            ))}
                          </div>
                        )}
                        <div
                          style={{
                            padding: "12px 24px",
                            borderBottom: `1px solid ${COLOR.darker}`,
                            backgroundColor: COLOR.darkest,
                          }}
                        >
                          <h4
                            style={{
                              margin: 0,
                              fontSize: FONT.body3.size,
                              fontWeight: 600,
                              color: COLOR.white,
                            }}
                          >
                            {tablePreview.table?.display_name ||
                              tablePreview.table?.table_name ||
                              "Table"}
                          </h4>
                          {tablePreview.table?.description && (
                            <p
                              style={{
                                margin: "4px 0 0",
                                fontSize: 12,
                                color: COLOR.medium,
                              }}
                            >
                              {tablePreview.table.description}
                            </p>
                          )}
                        </div>
                        {loadingPreview ? (
                          <KbTableSkeleton rows={8} />
                        ) : (
                          <div className="flex-1 overflow-auto min-h-0">
                            <table
                              className="min-w-full"
                              style={{ fontSize: 13, fontFamily: FONT.family }}
                            >
                              <thead className="sticky top-0 z-10">
                                <tr
                                  style={{
                                    backgroundColor: COLOR.darkest,
                                    borderBottom: `1px solid ${COLOR.darker}`,
                                  }}
                                >
                                  {(tablePreview.table?.columns || []).map(
                                    (col, i) => (
                                      <th
                                        key={i}
                                        className="text-left whitespace-nowrap"
                                        style={{
                                          padding: "10px 12px",
                                          color: COLOR.light,
                                          fontWeight: 600,
                                        }}
                                      >
                                        <span style={{ marginRight: 6 }}>
                                          {col.display_name || col.column_name}
                                        </span>
                                        <KbDataTypeBadge
                                          dataType={col.data_type}
                                        />
                                        {col.id && (
                                          <button
                                            type="button"
                                            onClick={(e) =>
                                              openColumnDescPopover(e, col)
                                            }
                                            title={
                                              col.description
                                                ? `Description: ${col.description}`
                                                : "Add description"
                                            }
                                            style={{
                                              marginLeft: 6,
                                              padding: 2,
                                              border: "none",
                                              borderRadius: 4,
                                              backgroundColor: col.description
                                                ? "rgba(22,106,197,0.15)"
                                                : "transparent",
                                              color: col.description
                                                ? "#7eb8ff"
                                                : COLOR.dark,
                                              cursor: "pointer",
                                              verticalAlign: "middle",
                                            }}
                                          >
                                            <AppIcon
                                              name="info"
                                              size={14}
                                              color="currentColor"
                                              weight="fill"
                                            />
                                          </button>
                                        )}
                                      </th>
                                    ),
                                  )}
                                </tr>
                              </thead>
                              <tbody>
                                {(tablePreview.rows || []).map((row, ri) => (
                                  <tr
                                    key={ri}
                                    style={{
                                      borderBottom: `1px solid ${COLOR.darker}`,
                                    }}
                                    onMouseEnter={(e) => {
                                      e.currentTarget.style.backgroundColor =
                                        "rgba(255,255,255,0.03)";
                                    }}
                                    onMouseLeave={(e) => {
                                      e.currentTarget.style.backgroundColor =
                                        "transparent";
                                    }}
                                  >
                                    {(tablePreview.table?.columns || []).map(
                                      (col, ci) => (
                                        <td
                                          key={ci}
                                          className="whitespace-nowrap max-w-[200px] truncate"
                                          style={{
                                            padding: "8px 12px",
                                            color: COLOR.white,
                                          }}
                                        >
                                          {Array.isArray(row)
                                            ? row[ci] != null
                                              ? String(row[ci])
                                              : ""
                                            : (row[col.column_name] ?? "")}
                                        </td>
                                      ),
                                    )}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                            {tablePreview.rows?.length === 0 && (
                              <p
                                style={{
                                  fontSize: FONT.body3.size,
                                  color: COLOR.medium,
                                  padding: 24,
                                  textAlign: "center",
                                }}
                              >
                                No rows
                              </p>
                            )}
                          </div>
                        )}
                        <KbPaginationFooter
                          label={`${tablePreview.table?.display_name || tablePreview.table?.table_name || "Table"}: ${tablePreview.total_rows ?? 0} rows · Page ${tablePreview.page || previewPage} of ${tablePreview.total_pages || 1}`}
                          page={previewPage}
                          totalPages={tablePreview.total_pages || 1}
                          onPrev={() =>
                            handlePreviewPageChange(previewPage - 1)
                          }
                          onNext={() =>
                            handlePreviewPageChange(previewPage + 1)
                          }
                          disabled={loadingPreview}
                        />
                      </div>
                    ) : (
                      <div className="flex flex-col items-center justify-center flex-1 text-center">
                        <ApexShellEmpty
                          description="No table data available."
                          style={{ marginTop: 32 }}
                        />
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    {loadingChunks ? (
                      <div
                        className="flex-1 overflow-y-auto"
                        style={{ padding: "16px 24px" }}
                      >
                        {[0, 1, 2, 3, 4].map((i) => (
                          <div key={i} style={{ marginBottom: 8 }}>
                            <ApexSkeleton
                              width="100%"
                              height={56}
                              radius={KB_DETAIL.chunkRowRadius}
                            />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="flex flex-col flex-1 min-h-0">
                        <div
                          className="flex-1 overflow-y-auto"
                          style={{ padding: "12px 24px" }}
                        >
                          {chunkList.length === 0 ? (
                            <ApexShellEmpty
                              description={
                                chunksSearch
                                  ? "No chunks match your search."
                                  : "No chunks available."
                              }
                              style={{ marginTop: 32 }}
                            />
                          ) : (
                            <div
                              style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: 8,
                              }}
                            >
                              {chunkList.map((chunk) => {
                                const expanded =
                                  expandedChunkId === chunk.chunk_id;
                                const text = chunk.chunk_text || "";
                                const needsTruncate =
                                  text.length > KB_DETAIL.chunkPreviewChars;
                                const displayText =
                                  expanded || !needsTruncate
                                    ? text
                                    : `${text.slice(0, KB_DETAIL.chunkPreviewChars).trim()}…`;
                                return (
                                  <div
                                    key={chunk.chunk_id}
                                    role="button"
                                    tabIndex={0}
                                    onClick={() =>
                                      setExpandedChunkId(
                                        expanded ? null : chunk.chunk_id,
                                      )
                                    }
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter" || e.key === " ") {
                                        e.preventDefault();
                                        setExpandedChunkId(
                                          expanded ? null : chunk.chunk_id,
                                        );
                                      }
                                    }}
                                    style={{
                                      padding: "12px 14px",
                                      borderRadius: KB_DETAIL.chunkRowRadius,
                                      backgroundColor: expanded
                                        ? "rgba(255,255,255,0.04)"
                                        : COLOR.darkest,
                                      border: `1px solid ${expanded ? COLOR.darker : "transparent"}`,
                                      cursor: "pointer",
                                      transition:
                                        "background-color 150ms, border-color 150ms",
                                    }}
                                  >
                                    <div className="flex items-center justify-between gap-3">
                                      <span
                                        style={{
                                          fontSize: FONT.body3.size,
                                          fontWeight: 600,
                                          color: COLOR.white,
                                          fontVariantNumeric: "tabular-nums",
                                        }}
                                      >
                                        Chunk {chunk.chunk_index + 1}
                                      </span>
                                      <div
                                        className="flex items-center"
                                        style={{ gap: 8, flexShrink: 0 }}
                                      >
                                        <span
                                          style={{
                                            fontSize: 12,
                                            color: COLOR.medium,
                                          }}
                                        >
                                          {chunk.chunk_size} chars
                                        </span>
                                        <AppIcon
                                          name="caretDown"
                                          size={14}
                                          color={COLOR.medium}
                                          style={{
                                            transform: expanded
                                              ? "rotate(180deg)"
                                              : "none",
                                            transition: "transform 150ms",
                                          }}
                                        />
                                      </div>
                                    </div>
                                    <p
                                      className="whitespace-pre-wrap"
                                      style={{
                                        margin: "8px 0 0",
                                        fontSize: 13,
                                        lineHeight: "20px",
                                        fontFamily: KB_MONO,
                                        color: COLOR.white,
                                        maxHeight: expanded ? "none" : 72,
                                        overflow: expanded
                                          ? "visible"
                                          : "hidden",
                                      }}
                                    >
                                      {displayText}
                                    </p>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                        <KbPaginationFooter
                          label={`${chunkTotal} chunks · Page ${chunksPage} of ${chunkTotalPages}`}
                          page={chunksPage}
                          totalPages={chunkTotalPages}
                          onPrev={() =>
                            loadChunks(
                              selectedDoc.id,
                              chunksPage - 1,
                              chunksSearch,
                            )
                          }
                          onNext={() =>
                            loadChunks(
                              selectedDoc.id,
                              chunksPage + 1,
                              chunksSearch,
                            )
                          }
                          disabled={loadingChunks}
                        />
                      </div>
                    )}
                  </>
                )}
              </>
            ) : (
              <div className="flex items-center justify-center h-full px-6">
                <ApexShellEmpty
                  title="No document selected"
                  description="Choose a document from the list to preview its chunks or table data."
                />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Expanded Table Preview Overlay */}
      {previewExpanded && tablePreview && selectedDoc?.is_structured && (
        <div
          className="fixed inset-0 flex items-center justify-center p-6"
          style={{ zIndex: 50, backgroundColor: "rgba(0,0,0,0.65)" }}
          onClick={() => setPreviewExpanded(false)}
        >
          <div
            data-theme="apex-dark"
            className="w-full h-full flex flex-col"
            style={{
              maxWidth: "95vw",
              maxHeight: "95vh",
              background: `linear-gradient(135deg, ${COLOR.darkest} 0%, ${COLOR.black} 100%)`,
              border: `1px solid ${COLOR.darker}`,
              borderRadius: KB_DETAIL.cardRadius,
              boxShadow: "0 12px 40px rgba(0,0,0,0.55)",
              fontFamily: FONT.family,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              className="flex items-center justify-between flex-shrink-0"
              style={{
                padding: "16px 24px",
                borderBottom: `1px solid ${COLOR.darker}`,
              }}
            >
              <div className="min-w-0">
                <h3
                  style={{
                    margin: 0,
                    color: COLOR.white,
                    fontSize: FONT.body1Bold.size,
                    fontWeight: 700,
                  }}
                >
                  {selectedDoc.file_name}
                </h3>
                <p
                  style={{
                    margin: "4px 0 0",
                    fontSize: FONT.body3.size,
                    color: COLOR.medium,
                  }}
                >
                  {tablePreview.table?.display_name ||
                    tablePreview.table?.table_name ||
                    "Table"}
                  {tablePreview.table?.description &&
                    ` — ${tablePreview.table.description}`}
                </p>
              </div>
              <KbCloseButton
                onClick={() => setPreviewExpanded(false)}
                title="Collapse"
                size={22}
              />
            </div>

            {(tablePreview.tables || []).length > 1 && (
              <div
                className="flex flex-wrap flex-shrink-0"
                style={{
                  padding: "8px 16px 0",
                  gap: 4,
                  borderBottom: `1px solid ${COLOR.darker}`,
                }}
              >
                {tablePreview.tables.map((t) => (
                  <KbTab
                    key={t.id}
                    active={
                      (activePreviewTab || tablePreview.tables[0]?.id) === t.id
                    }
                    onClick={() => handlePreviewTabChange(t.id)}
                    count={t.row_count ?? "?"}
                  >
                    {t.display_name ||
                      t.table_name ||
                      t.source_sheet ||
                      "Table"}
                  </KbTab>
                ))}
              </div>
            )}

            {loadingPreview ? (
              <div className="flex-1 flex items-center justify-center">
                <KbRoseSpinner size={40} />
              </div>
            ) : (
              <div className="flex-1 overflow-auto min-h-0">
                <table
                  className="min-w-full"
                  style={{ fontSize: 14, fontFamily: FONT.family }}
                >
                  <thead className="sticky top-0 z-10">
                    <tr
                      style={{
                        backgroundColor: COLOR.darkest,
                        borderBottom: `1px solid ${COLOR.darker}`,
                      }}
                    >
                      {(tablePreview.table?.columns || []).map((col, i) => (
                        <th
                          key={i}
                          className="text-left whitespace-nowrap"
                          style={{ padding: "12px 16px", color: COLOR.light }}
                        >
                          <span style={{ marginRight: 8 }}>
                            {col.display_name || col.column_name}
                          </span>
                          <KbDataTypeBadge dataType={col.data_type} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(tablePreview.rows || []).map((row, ri) => (
                      <tr
                        key={ri}
                        style={{ borderBottom: `1px solid ${COLOR.darker}` }}
                      >
                        {(tablePreview.table?.columns || []).map((col, ci) => (
                          <td
                            key={ci}
                            className="whitespace-nowrap"
                            style={{ padding: "10px 16px", color: COLOR.white }}
                          >
                            {Array.isArray(row)
                              ? row[ci] != null
                                ? String(row[ci])
                                : ""
                              : (row[col.column_name] ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <KbPaginationFooter
              label={`${tablePreview.total_rows ?? 0} rows · Page ${previewPage} of ${tablePreview.total_pages || 1}`}
              page={previewPage}
              totalPages={tablePreview.total_pages || 1}
              onPrev={() => handlePreviewPageChange(previewPage - 1)}
              onNext={() => handlePreviewPageChange(previewPage + 1)}
              disabled={loadingPreview}
            />
          </div>
        </div>
      )}

      {/* Schema Editor Modal */}
      {schemaModal &&
        (() => {
          if (schemaModal.loading) {
            return (
              <div
                className="fixed inset-0 flex items-center justify-center"
                style={{ zIndex: 50, backgroundColor: "rgba(0,0,0,0.65)" }}
              >
                <div
                  data-theme="apex-dark"
                  style={{
                    backgroundColor: COLOR.darkest,
                    border: `1px solid ${COLOR.darker}`,
                    borderRadius: KB_DETAIL.cardRadius,
                    padding: 40,
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: 16,
                    fontFamily: FONT.family,
                  }}
                >
                  <KbRoseSpinner size={40} />
                  <p
                    style={{
                      margin: 0,
                      fontSize: FONT.body2.size,
                      fontWeight: 600,
                      color: COLOR.white,
                    }}
                  >
                    Inferring schema and descriptions…
                  </p>
                  <p style={{ margin: 0, fontSize: 12, color: COLOR.medium }}>
                    Analyzing file structure with AI
                  </p>
                </div>
              </div>
            );
          }
          const tableIdx = activeSheetTab;
          const table = schemaModal.tables?.[tableIdx];
          const tabCount = schemaModal.tables?.length || 0;
          return (
            <div
              className="fixed inset-0 flex items-center justify-center overflow-y-auto p-4"
              style={{ zIndex: 50, backgroundColor: "rgba(0,0,0,0.65)" }}
            >
              <div
                data-theme="apex-dark"
                className="w-full flex flex-col my-8"
                style={{
                  maxWidth: 960,
                  maxHeight: "90vh",
                  background: `linear-gradient(135deg, ${COLOR.darkest} 0%, ${COLOR.black} 100%)`,
                  border: `1px solid ${COLOR.darker}`,
                  borderRadius: KB_DETAIL.cardRadius,
                  boxShadow: "0 12px 40px rgba(0,0,0,0.55)",
                  fontFamily: FONT.family,
                }}
              >
                <div
                  style={{
                    padding: "20px 24px",
                    borderBottom: `1px solid ${COLOR.darker}`,
                  }}
                >
                  <h3
                    style={{
                      margin: 0,
                      color: COLOR.white,
                      fontSize: FONT.body1Bold.size,
                      fontWeight: 700,
                    }}
                  >
                    Configure structured data
                  </h3>
                  <p
                    style={{
                      margin: "6px 0 0",
                      color: COLOR.medium,
                      fontSize: FONT.body3.size,
                    }}
                  >
                    Review and edit column types and descriptions before loading
                    data.
                  </p>
                </div>

                {tabCount > 1 && (
                  <div
                    className="flex flex-wrap"
                    style={{ padding: "8px 16px 0", gap: 4 }}
                  >
                    {schemaModal.tables.map((t, idx) => (
                      <div
                        key={idx}
                        className="flex items-center"
                        style={{ gap: 2 }}
                      >
                        <KbTab
                          active={idx === activeSheetTab}
                          onClick={() => setActiveSheetTab(idx)}
                        >
                          {t.sheet_name || t.table_name || `Sheet ${idx + 1}`}
                        </KbTab>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            removeSchemaTable(idx);
                          }}
                          title={`Remove ${t.sheet_name || t.table_name || "this sheet"}`}
                          style={{
                            width: 22,
                            height: 22,
                            border: "none",
                            borderRadius: 6,
                            backgroundColor: "transparent",
                            color: COLOR.dark,
                            cursor: "pointer",
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.backgroundColor =
                              COLOR.errorBg;
                            e.currentTarget.style.color = COLOR.errorFg;
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.backgroundColor =
                              "transparent";
                            e.currentTarget.style.color = COLOR.dark;
                          }}
                        >
                          <AppIcon
                            name="close"
                            size={12}
                            color="currentColor"
                            weight="bold"
                          />
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5 border-t border-[#464646]">
                  {table && (
                    <>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-sm font-medium text-[#dadada] mb-1">
                            Table name
                          </label>
                          <input
                            type="text"
                            className="force-white-text w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:border-[#d93854]"
                            value={table.table_name || ""}
                            onChange={(e) =>
                              updateSchemaTable(
                                tableIdx,
                                "table_name",
                                e.target.value,
                              )
                            }
                            style={{
                              borderColor: getTableNameConflict(tableIdx)
                                ? COLOR.rose
                                : COLOR.darker,
                              backgroundColor: COLOR.black,
                              borderRadius: KB_DETAIL.buttonRadius,
                            }}
                          />
                          {getTableNameConflict(tableIdx) && (
                            <p className="text-xs text-red-600 mt-1">
                              {getTableNameConflict(tableIdx)}
                            </p>
                          )}
                        </div>
                        <div className="text-xs text-[#6b6b6b] self-end pb-2">
                          {tabCount > 1 &&
                            `Sheet ${tableIdx + 1} of ${tabCount}`}
                          {table.total_rows != null &&
                            ` · ${table.total_rows} rows`}
                        </div>
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-[#dadada] mb-1">
                          Table description
                        </label>
                        <textarea
                          className="force-white-text w-full px-3 py-2 border resize-y min-h-[72px] text-sm focus:outline-none focus:border-[#d93854]"
                          value={table.table_description || ""}
                          onChange={(e) => {
                            updateSchemaTable(
                              tableIdx,
                              "table_description",
                              e.target.value,
                            );
                            e.target.style.height = "auto";
                            e.target.style.height = `${e.target.scrollHeight}px`;
                          }}
                          rows={3}
                          style={{
                            borderColor: COLOR.darker,
                            backgroundColor: COLOR.black,
                            borderRadius: KB_DETAIL.buttonRadius,
                            color: COLOR.white,
                          }}
                        />
                      </div>
                      {table.sample_rows && table.sample_rows.length > 0 && (
                        <div>
                          <label className="block text-sm font-medium text-[#dadada] mb-2">
                            Data preview
                          </label>
                          <div className="overflow-x-auto border border-[#464646] rounded-lg max-h-[200px]">
                            <table className="min-w-full text-xs">
                              <thead className="sticky top-0">
                                <tr className="bg-[#222222]">
                                  {(table.headers || []).map((h, i) => (
                                    <th
                                      key={i}
                                      className="px-2 py-1.5 text-left font-medium text-[#dadada] whitespace-nowrap"
                                    >
                                      {h}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {table.sample_rows
                                  .slice(0, 5)
                                  .map((row, ri) => (
                                    <tr
                                      key={ri}
                                      className="border-t border-[#333333]"
                                    >
                                      {(table.headers || []).map((h, i) => (
                                        <td
                                          key={i}
                                          className="px-2 py-1.5 text-[#b5b5b5] whitespace-nowrap max-w-[180px] truncate"
                                        >
                                          {Array.isArray(row) ? row[i] : row[h]}
                                        </td>
                                      ))}
                                    </tr>
                                  ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}
                      <div>
                        <label className="block text-sm font-medium text-[#dadada] mb-2">
                          Columns
                        </label>
                        <div className="overflow-x-auto border border-[#464646] rounded-lg">
                          <table className="min-w-full text-sm">
                            <thead>
                              <tr className="bg-[#222222]">
                                <th className="px-3 py-2 text-left font-medium text-[#dadada] w-[180px]">
                                  Column
                                </th>
                                <th className="px-3 py-2 text-left font-medium text-[#dadada] w-[120px]">
                                  Data type
                                </th>
                                <th className="px-3 py-2 text-left font-medium text-[#dadada]">
                                  Description
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {(table.columns || []).map((col, colIdx) => (
                                <tr
                                  key={colIdx}
                                  className="border-t border-[#464646]"
                                >
                                  <td className="px-3 py-2 text-[#dadada] font-mono text-xs">
                                    {col.column_name}
                                  </td>
                                  <td className="px-3 py-2">
                                    <select
                                      value={col.data_type || "text"}
                                      onChange={(e) =>
                                        updateSchemaColumn(
                                          tableIdx,
                                          colIdx,
                                          "data_type",
                                          e.target.value,
                                        )
                                      }
                                      className="w-full px-2 py-1.5 border border-[#464646] rounded text-sm text-white focus:ring-2 focus:ring-blue-500"
                                    >
                                      {[
                                        "text",
                                        "integer",
                                        "numeric",
                                        "date",
                                        "datetime",
                                        "boolean",
                                      ].map((dt) => (
                                        <option key={dt} value={dt}>
                                          {dt}
                                        </option>
                                      ))}
                                    </select>
                                  </td>
                                  <td className="px-3 py-2">
                                    <input
                                      type="text"
                                      value={col.description || ""}
                                      onChange={(e) =>
                                        updateSchemaColumn(
                                          tableIdx,
                                          colIdx,
                                          "description",
                                          e.target.value,
                                        )
                                      }
                                      className="w-full px-2 py-1.5 border border-[#464646] rounded text-sm text-white focus:ring-2 focus:ring-blue-500"
                                      placeholder="Column description..."
                                    />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </>
                  )}
                </div>
                <div className="px-6 py-4 border-t border-[#464646] flex gap-3">
                  <Button
                    onClick={handleConfirmSchema}
                    disabled={
                      confirmingSchema ||
                      schemaModal.loading ||
                      hasAnyTableConflict()
                    }
                    className="flex-1"
                  >
                    {confirmingSchema ? (
                      <>
                        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                        Loading data...
                      </>
                    ) : (
                      `Confirm & Load${tabCount > 1 ? ` (${tabCount} tables)` : ""}`
                    )}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={handleCancelSchema}
                    disabled={confirmingSchema}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            </div>
          );
        })()}

      {/* Relationship Diagram Overlay */}
      {showRelEditor && (
        <div
          className="fixed inset-0 flex items-center justify-center p-4"
          style={{ zIndex: 50, backgroundColor: "rgba(0,0,0,0.65)" }}
        >
          <div
            data-theme="apex-dark"
            className="w-full h-full flex flex-col overflow-hidden"
            style={{
              maxWidth: "94vw",
              maxHeight: "90vh",
              backgroundColor: COLOR.black,
              border: `1px solid ${COLOR.darker}`,
              borderRadius: KB_DETAIL.cardRadius,
              boxShadow: "0 12px 40px rgba(0,0,0,0.55)",
              fontFamily: FONT.family,
            }}
          >
            <div
              className="flex items-center justify-between flex-shrink-0"
              style={{
                padding: "12px 20px",
                borderBottom: `1px solid ${COLOR.darker}`,
                backgroundColor: COLOR.darkest,
              }}
            >
              <div className="flex items-center" style={{ gap: 12 }}>
                <AppIcon name="share" size={20} color={COLOR.medium} />
                <div>
                  <h3
                    style={{
                      margin: 0,
                      fontSize: FONT.body2.size,
                      fontWeight: 700,
                      color: COLOR.white,
                    }}
                  >
                    Semantic model
                  </h3>
                  <p
                    style={{
                      margin: "2px 0 0",
                      fontSize: 11,
                      color: COLOR.medium,
                    }}
                  >
                    Drag columns between tables to create relationships. Click a
                    line to edit or delete.
                  </p>
                </div>
              </div>
              <div className="flex items-center" style={{ gap: 10 }}>
                {relError && (
                  <span
                    style={{
                      fontSize: 12,
                      color: COLOR.errorFg,
                      backgroundColor: COLOR.errorBg,
                      padding: "4px 10px",
                      borderRadius: 6,
                      border: `1px solid rgba(217, 56, 84, 0.3)`,
                    }}
                  >
                    {relError}
                  </span>
                )}
                {relSaving && (
                  <div
                    className="flex items-center"
                    style={{ gap: 8, fontSize: 12, color: COLOR.medium }}
                  >
                    <KbRoseSpinner size={14} />
                    Saving…
                  </div>
                )}
                <span style={{ fontSize: 12, color: COLOR.medium }}>
                  {relationships.length} relationship
                  {relationships.length !== 1 ? "s" : ""}
                </span>
                <KbCloseButton
                  onClick={() => {
                    setShowRelEditor(false);
                    setRelError("");
                    setSelectedRel(null);
                    setEditRelModal(null);
                    setColTooltip(null);
                  }}
                />
              </div>
            </div>

            {relLoading ? (
              <div className="flex-1 flex items-center justify-center">
                <KbRoseSpinner size={40} />
              </div>
            ) : (
              <div
                ref={diagramRef}
                className="flex-1 relative overflow-auto"
                style={{
                  cursor: connecting
                    ? "crosshair"
                    : draggingTable
                      ? "grabbing"
                      : "default",
                  backgroundColor: COLOR.black,
                }}
                onClick={() => {
                  setSelectedRel(null);
                  setEditRelModal(null);
                }}
              >
                {/* SVG relationship lines */}
                <svg
                  className="absolute inset-0 w-full h-full pointer-events-none"
                  style={{ minWidth: 2000, minHeight: 1400 }}
                >
                  <defs>
                    <marker
                      id="rel-arrow"
                      markerWidth="8"
                      markerHeight="6"
                      refX="7"
                      refY="3"
                      orient="auto"
                    >
                      <path
                        d="M0,0 L8,3 L0,6"
                        fill="none"
                        stroke="#6b7280"
                        strokeWidth="1"
                      />
                    </marker>
                    <marker
                      id="rel-arrow-sel"
                      markerWidth="8"
                      markerHeight="6"
                      refX="7"
                      refY="3"
                      orient="auto"
                    >
                      <path
                        d="M0,0 L8,3 L0,6"
                        fill="none"
                        stroke="#3b82f6"
                        strokeWidth="1.5"
                      />
                    </marker>
                    <marker
                      id="rel-one"
                      markerWidth="10"
                      markerHeight="12"
                      refX="5"
                      refY="6"
                      orient="auto"
                    >
                      <line
                        x1="5"
                        y1="0"
                        x2="5"
                        y2="12"
                        stroke="#6b7280"
                        strokeWidth="1.5"
                      />
                    </marker>
                    <marker
                      id="rel-many"
                      markerWidth="12"
                      markerHeight="12"
                      refX="6"
                      refY="6"
                      orient="auto"
                    >
                      <path
                        d="M0,6 L10,0 M0,6 L10,12 M0,6 L10,6"
                        fill="none"
                        stroke="#6b7280"
                        strokeWidth="1"
                      />
                    </marker>
                  </defs>
                  {relationships.map((rel) => {
                    const line = getRelLine(rel);
                    if (!line) return null;
                    const { from, to } = line;
                    const dx = to.x - from.x;
                    const midX = from.x + dx * 0.5;
                    const isSelected = selectedRel === rel.id;
                    return (
                      <g key={rel.id}>
                        {/* Invisible thick line for easier clicking */}
                        <path
                          d={`M${from.x},${from.y} C${midX},${from.y} ${midX},${to.y} ${to.x},${to.y}`}
                          fill="none"
                          stroke="transparent"
                          strokeWidth="14"
                          style={{ pointerEvents: "stroke", cursor: "pointer" }}
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedRel(rel.id);
                            setEditRelModal(rel);
                          }}
                        />
                        <path
                          d={`M${from.x},${from.y} C${midX},${from.y} ${midX},${to.y} ${to.x},${to.y}`}
                          fill="none"
                          stroke={isSelected ? COLOR.rose : COLOR.darker}
                          strokeWidth={isSelected ? 2.5 : 1.5}
                          markerEnd={
                            isSelected
                              ? "url(#rel-arrow-sel)"
                              : "url(#rel-arrow)"
                          }
                          style={{ pointerEvents: "none" }}
                        />
                        {/* Relationship type badge on the line */}
                        <text
                          x={midX}
                          y={(from.y + to.y) / 2 - 6}
                          textAnchor="middle"
                          className="text-[9px] fill-gray-400 select-none pointer-events-none"
                        >
                          {rel.relationship_type?.replace(/_/g, ":")}
                        </text>
                      </g>
                    );
                  })}
                  {/* Temporary connecting line while dragging */}
                  {connecting &&
                    (() => {
                      const anchor = getColumnAnchor(
                        connecting.sourceTableId,
                        connecting.sourceColumnId,
                        "right",
                      );
                      return (
                        <line
                          x1={anchor.x}
                          y1={anchor.y}
                          x2={connecting.mouseX}
                          y2={connecting.mouseY}
                          stroke={COLOR.rose}
                          strokeWidth="2"
                          strokeDasharray="6,3"
                          style={{ pointerEvents: "none" }}
                        />
                      );
                    })()}
                </svg>

                {/* Floating table cards */}
                {relTables.map((table) => {
                  const pos = tablePositions[table.id];
                  if (!pos) return null;
                  return (
                    <div
                      key={table.id}
                      className="absolute select-none"
                      style={{
                        left: pos.x,
                        top: pos.y,
                        width: TABLE_CARD_W,
                        zIndex: draggingTable === table.id ? 20 : 10,
                      }}
                      onMouseDown={(e) => onTableMouseDown(e, table.id)}
                    >
                      <div
                        className="rounded-lg border overflow-hidden transition-shadow"
                        style={{
                          backgroundColor: COLOR.darkest,
                          borderColor:
                            draggingTable === table.id
                              ? COLOR.rose
                              : COLOR.darker,
                          boxShadow:
                            draggingTable === table.id
                              ? `0 0 16px rgba(217, 56, 84, 0.2)`
                              : "none",
                        }}
                      >
                        <div
                          className="flex items-center cursor-grab active:cursor-grabbing"
                          style={{
                            height: TABLE_HEADER_H,
                            padding: "0 12px",
                            gap: 8,
                            backgroundColor: "rgba(255,255,255,0.04)",
                            borderBottom: `1px solid ${COLOR.darker}`,
                          }}
                        >
                          <AppIcon
                            name="excel-generator"
                            size={14}
                            color={COLOR.medium}
                          />
                          <span className="text-xs font-semibold text-white truncate">
                            {table.display_name || table.table_name}
                          </span>
                          {table.description && (
                            <span
                              className="ml-auto text-[#6b6b6b] hover:text-[#dadada] cursor-help flex-shrink-0"
                              title={table.description}
                            >
                              <AppIcon
                                name="info"
                                size={12}
                                color={COLOR.medium}
                                weight="fill"
                              />
                            </span>
                          )}
                        </div>
                        {/* Columns */}
                        <div style={{ borderTop: `1px solid ${COLOR.darker}` }}>
                          {(table.columns || []).map((col) => (
                            <div
                              key={col.id}
                              className="group relative flex items-center px-1 transition-colors"
                              style={{
                                height: COL_ROW_H,
                                borderBottom: `1px solid ${COLOR.darker}`,
                              }}
                              onMouseEnter={(e) => {
                                e.currentTarget.style.backgroundColor =
                                  "rgba(217, 56, 84, 0.06)";
                                if (col.description) {
                                  const rect =
                                    e.currentTarget.getBoundingClientRect();
                                  const diagRect =
                                    diagramRef.current?.getBoundingClientRect();
                                  setColTooltip({
                                    text: col.description,
                                    x: rect.right - (diagRect?.left || 0) + 6,
                                    y: rect.top - (diagRect?.top || 0),
                                  });
                                }
                              }}
                              onMouseLeave={(e) => {
                                e.currentTarget.style.backgroundColor =
                                  "transparent";
                                setColTooltip(null);
                              }}
                            >
                              {/* Left handle */}
                              <div
                                data-col-handle
                                data-table-id={table.id}
                                data-col-id={col.id}
                                className="w-3 h-3 rounded-full border-2 cursor-crosshair flex-shrink-0 transition-colors"
                                style={{
                                  borderColor: COLOR.darker,
                                  backgroundColor: COLOR.darkest,
                                }}
                                onMouseDown={(e) =>
                                  onColHandleMouseDown(e, table.id, col.id)
                                }
                              />
                              <span
                                className="ml-2 truncate flex-1"
                                style={{
                                  fontSize: 11,
                                  fontFamily: KB_MONO,
                                  color: COLOR.light,
                                }}
                              >
                                {col.column_name}
                              </span>
                              <span className="mr-1 flex-shrink-0">
                                <KbDataTypeBadge dataType={col.data_type} />
                              </span>
                              {/* Right handle */}
                              <div
                                data-col-handle
                                data-table-id={table.id}
                                data-col-id={col.id}
                                className="w-3 h-3 rounded-full border-2 cursor-crosshair flex-shrink-0 transition-colors"
                                style={{
                                  borderColor: COLOR.darker,
                                  backgroundColor: COLOR.darkest,
                                }}
                                onMouseDown={(e) =>
                                  onColHandleMouseDown(e, table.id, col.id)
                                }
                              />
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  );
                })}

                {/* Column description tooltip */}
                {colTooltip && (
                  <div
                    className="absolute z-50 px-3 py-1.5 bg-[#1a1a1a] text-white text-[11px] border border-[#464646] rounded-lg shadow-lg max-w-[220px] pointer-events-none"
                    style={{ left: colTooltip.x, top: colTooltip.y }}
                  >
                    {colTooltip.text}
                  </div>
                )}

                {/* Edit/Delete relationship popover */}
                {editRelModal &&
                  (() => {
                    const line = getRelLine(editRelModal);
                    if (!line) return null;
                    const cx = (line.from.x + line.to.x) / 2;
                    const cy = (line.from.y + line.to.y) / 2;
                    return (
                      <div
                        className="absolute z-40 bg-[#1a1a1a] rounded-lg shadow-xl border border-[#464646] p-3 w-[240px]"
                        style={{ left: cx - 120, top: cy + 14 }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="text-[11px] text-[#6b6b6b] mb-2 font-mono">
                          {editRelModal.source_table_name}.
                          {editRelModal.source_column_name}
                          <span className="mx-1 text-[#6b6b6b]">&rarr;</span>
                          {editRelModal.target_table_name}.
                          {editRelModal.target_column_name}
                        </div>
                        <label className="block text-[10px] font-medium text-[#6b6b6b] uppercase tracking-wide mb-1">
                          Type
                        </label>
                        <select
                          value={editRelModal.relationship_type}
                          onChange={(e) =>
                            handleUpdateRelType(editRelModal.id, e.target.value)
                          }
                          disabled={relSaving}
                          className="w-full px-2 py-1.5 border border-[#464646] rounded text-xs text-white mb-2 focus:ring-1 focus:ring-blue-400 focus:border-blue-400"
                        >
                          <option value="one_to_one">One to One</option>
                          <option value="one_to_many">One to Many</option>
                          <option value="many_to_one">Many to One</option>
                        </select>
                        <button
                          onClick={() =>
                            handleDeleteRelationship(editRelModal.id)
                          }
                          className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs text-red-500 hover:bg-red-900/20 rounded transition-colors border border-red-500/30"
                        >
                          <svg
                            className="w-3.5 h-3.5"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                            />
                          </svg>
                          Remove Relationship
                        </button>
                      </div>
                    );
                  })()}
              </div>
            )}
          </div>
        </div>
      )}

      <ConfirmModal
        isOpen={Boolean(deletingDoc)}
        title="Delete document"
        message={
          deletingDoc
            ? `Are you sure you want to delete "${deletingDoc.file_name}"? This cannot be undone.`
            : ""
        }
        confirmText="Delete"
        cancelText="Cancel"
        variant="danger"
        onConfirm={handleDeleteDoc}
        onCancel={() => setDeletingDoc(null)}
      />

      {/* Chunking Config Modal (shown before uploading non-structured files) */}
      {chunkingModal && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={() => setChunkingModal(null)}
        >
          <div
            data-theme="apex-dark"
            className="bg-[#1a1a1a] border border-[#464646] rounded-xl p-6 max-w-lg w-full mx-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-white mb-1">
              Configure Chunking
            </h3>
            <p className="text-sm text-[#b5b5b5] mb-5">
              Choose how to split{" "}
              {chunkingModal.files.length === 1 ? (
                <span className="font-medium text-white">
                  {chunkingModal.files[0].name}
                </span>
              ) : (
                <span className="font-medium text-white">
                  {chunkingModal.files.length} files
                </span>
              )}{" "}
              into chunks for embedding.
            </p>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-white mb-2">
                  Chunking Method
                </label>
                <Select
                  value={chunkingConfig.chunking_method}
                  onChange={(e) => {
                    const m = e.target.value;
                    setChunkingConfig((prev) => ({
                      ...prev,
                      chunking_method: m,
                      chunk_overlap: m === "fixed_size" ? 200 : 0,
                    }));
                  }}
                >
                  <option value="fixed_size">Fixed Size</option>
                  <option value="recursive">Recursive (Recommended)</option>
                  <option value="sentence">Sentence</option>
                  <option value="paragraph">Paragraph</option>
                  <option value="page">Page (PDF, Word, PowerPoint)</option>
                  <option value="delimiter">Delimiter</option>
                  <option value="vision">
                    Vision AI (PDF, Word, PowerPoint)
                  </option>
                </Select>
              </div>

              {chunkingConfig.chunking_method === "vision" ? (
                <div className="space-y-4">
                  <div className="bg-purple-900/20 border border-purple-500/30 rounded-lg p-3">
                    <p className="text-xs text-purple-300 font-medium mb-1">
                      Vision AI Processing
                    </p>
                    <p className="text-xs text-purple-400">
                      Each page or slide is rendered as an image and analyzed by
                      a vision AI model. Best for complex layouts like org
                      charts, tables, diagrams, and presentations. Pages with no
                      relevant content are automatically skipped.
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-white mb-2">
                      Extraction Prompt <span className="text-red-500">*</span>
                    </label>
                    <textarea
                      value={visionConfig.prompt}
                      onChange={(e) =>
                        setVisionConfig((prev) => ({
                          ...prev,
                          prompt: e.target.value,
                        }))
                      }
                      placeholder="Describe what information to extract, e.g. 'Extract organizational structures, departments, leadership positions, and key insights from each slide'"
                      rows={3}
                      className="w-full rounded-lg border border-[#464646] bg-[#0d0d0d] text-white placeholder:text-[#6b6b6b] px-3 py-2 text-sm focus:border-[#d93854] focus:ring-1 focus:ring-[#d93854] focus:outline-none"
                    />
                    <p className="text-xs text-[#6b6b6b] mt-1">
                      Tell the AI what to look for on each page
                    </p>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-white mb-2">
                      Vision Model
                    </label>
                    <Select
                      value={visionConfig.model}
                      onChange={(e) =>
                        setVisionConfig((prev) => ({
                          ...prev,
                          model: e.target.value,
                        }))
                      }
                    >
                      <option value="vertex_ai.gemini-2.5-flash">
                        Gemini 2.5 Flash (Recommended)
                      </option>
                      <option value="vertex_ai.gemini-2.5-pro">
                        Gemini 2.5 Pro
                      </option>
                      <option value="bedrock.anthropic.claude-haiku-4-5">
                        Claude Haiku 4.5
                      </option>
                      <option value="bedrock.anthropic.claude-sonnet-4-5">
                        Claude Sonnet 4.5
                      </option>
                    </Select>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-white mb-2">
                      Output Schema (JSON, optional)
                    </label>
                    <textarea
                      value={visionConfig.output_schema_text}
                      onChange={(e) =>
                        setVisionConfig((prev) => ({
                          ...prev,
                          output_schema_text: e.target.value,
                        }))
                      }
                      placeholder={
                        '[\n  {"name": "page_type", "type": "string", "description": "Type of content"},\n  {"name": "summary", "type": "string", "description": "Brief summary"}\n]'
                      }
                      rows={4}
                      className="w-full rounded-lg border border-[#464646] bg-[#0d0d0d] text-white placeholder:text-[#6b6b6b] px-3 py-2 text-xs font-mono focus:border-[#d93854] focus:ring-1 focus:ring-[#d93854] focus:outline-none"
                    />
                    <p className="text-xs text-[#6b6b6b] mt-1">
                      Leave empty for free-form text extraction
                    </p>
                  </div>
                </div>
              ) : chunkingConfig.chunking_method === "page" ? (
                <div className="bg-blue-900/20 border border-blue-500/30 rounded-lg p-3">
                  <p className="text-xs text-blue-300 font-medium mb-1">
                    One chunk per page / slide
                  </p>
                  <p className="text-xs text-blue-400">
                    Each page (PDF, Word) or slide (PowerPoint) becomes a
                    separate chunk. Best for documents where page boundaries
                    carry semantic meaning. For file types without pages (TXT,
                    JSON, MD), falls back to recursive chunking.
                  </p>
                </div>
              ) : chunkingConfig.chunking_method === "delimiter" ? (
                <div>
                  <label className="block text-sm font-medium text-white mb-2">
                    Delimiter String
                  </label>
                  <Input
                    type="text"
                    value={chunkingConfig.delimiter}
                    onChange={(e) =>
                      setChunkingConfig((prev) => ({
                        ...prev,
                        delimiter: e.target.value,
                      }))
                    }
                    placeholder="e.g. ===END==="
                  />
                  <p className="text-xs text-[#b5b5b5] mt-1">
                    Text splits on this exact string; each segment becomes one
                    chunk
                  </p>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-white mb-2">
                      Chunk Size
                    </label>
                    <Input
                      type="number"
                      value={chunkingConfig.chunk_size}
                      onChange={(e) =>
                        setChunkingConfig((prev) => ({
                          ...prev,
                          chunk_size: e.target.value,
                        }))
                      }
                      min="100"
                      max="4000"
                    />
                    <p className="text-xs text-[#b5b5b5] mt-1">
                      Characters per chunk
                    </p>
                  </div>

                  {chunkingConfig.chunking_method === "fixed_size" && (
                    <div>
                      <label className="block text-sm font-medium text-white mb-2">
                        Chunk Overlap
                      </label>
                      <Input
                        type="number"
                        value={chunkingConfig.chunk_overlap}
                        onChange={(e) =>
                          setChunkingConfig((prev) => ({
                            ...prev,
                            chunk_overlap: e.target.value,
                          }))
                        }
                        min="0"
                        max="500"
                      />
                      <p className="text-xs text-[#b5b5b5] mt-1">
                        Overlap between chunks
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* Metadata Inference (hidden for vision mode — vision has its own schema) */}
              {chunkingConfig.chunking_method !== "vision" && (
                <div className="pt-3 border-t border-[#464646]">
                  <label className="flex items-center gap-3 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={inferMetadata}
                      onChange={(e) => {
                        setInferMetadata(e.target.checked);
                        if (!e.target.checked) setMetadataFields([]);
                      }}
                      className="h-4 w-4 rounded border-[#464646] text-primary focus:ring-primary"
                    />
                    <div>
                      <span className="text-sm font-medium text-white">
                        Infer metadata
                      </span>
                      <p className="text-xs text-[#6b6b6b]">
                        Use an LLM to extract structured fields from this
                        document
                      </p>
                    </div>
                  </label>
                </div>
              )}

              {inferMetadata && (
                <div className="space-y-3 bg-[#0d0d0d] rounded-lg p-3 border border-[#464646]">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-[#dadada]">
                      Metadata Fields
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setMetadataFields((prev) => [
                          ...prev,
                          {
                            name: "",
                            type: "string",
                            scope: "global",
                            description: "",
                          },
                        ])
                      }
                      className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium text-primary bg-[#1a1a1a] border border-[#464646] rounded-md hover:bg-[#1a1a1a] transition-colors"
                    >
                      + Add field
                    </button>
                  </div>

                  {metadataFields.length === 0 && (
                    <p className="text-xs text-[#6b6b6b] text-center py-1">
                      Click "Add field" to define metadata to extract.
                    </p>
                  )}

                  {metadataFields.map((field, idx) => (
                    <div
                      key={idx}
                      className="bg-[#1a1a1a] rounded-lg border border-[#464646] p-2 space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-[#6b6b6b]">
                          Field {idx + 1}
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            setMetadataFields((prev) =>
                              prev.filter((_, i) => i !== idx),
                            )
                          }
                          className="w-5 h-5 rounded hover:bg-red-900/20 text-[#6b6b6b] hover:text-red-500 flex items-center justify-center"
                        >
                          <svg
                            className="w-3.5 h-3.5"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M6 18L18 6M6 6l12 12"
                            />
                          </svg>
                        </button>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        <div>
                          <label className="block text-xs text-[#b5b5b5] mb-1">
                            Name *
                          </label>
                          <Input
                            type="text"
                            value={field.name}
                            onChange={(e) => {
                              const val = e.target.value.replace(
                                /[^a-zA-Z0-9_]/g,
                                "_",
                              );
                              setMetadataFields((prev) => {
                                const u = [...prev];
                                u[idx] = { ...u[idx], name: val };
                                return u;
                              });
                            }}
                            placeholder="field_name"
                            className="!text-xs !py-1"
                          />
                        </div>
                        <div>
                          <label className="block text-xs text-[#b5b5b5] mb-1">
                            Type
                          </label>
                          <Select
                            value={field.type}
                            onChange={(e) =>
                              setMetadataFields((prev) => {
                                const u = [...prev];
                                u[idx] = { ...u[idx], type: e.target.value };
                                return u;
                              })
                            }
                            className="!text-xs !py-1"
                          >
                            <option value="string">String</option>
                            <option value="number">Number</option>
                            <option value="date">Date</option>
                            <option value="boolean">Boolean</option>
                          </Select>
                        </div>
                        <div>
                          <label className="block text-xs text-[#b5b5b5] mb-1">
                            Scope
                          </label>
                          <Select
                            value={field.scope}
                            onChange={(e) =>
                              setMetadataFields((prev) => {
                                const u = [...prev];
                                u[idx] = { ...u[idx], scope: e.target.value };
                                return u;
                              })
                            }
                            className="!text-xs !py-1"
                          >
                            <option value="global">Global (doc)</option>
                            <option value="local">Local (chunk)</option>
                          </Select>
                        </div>
                      </div>
                      <Input
                        type="text"
                        value={field.description}
                        onChange={(e) =>
                          setMetadataFields((prev) => {
                            const u = [...prev];
                            u[idx] = { ...u[idx], description: e.target.value };
                            return u;
                          })
                        }
                        placeholder="Hint for the LLM, e.g. 'Publication date of the document'"
                        className="!text-xs !py-1"
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="flex gap-3 justify-end mt-6">
              <Button
                onClick={handleChunkingConfirm}
                disabled={
                  uploading ||
                  (chunkingConfig.chunking_method === "vision" &&
                    !visionConfig.prompt.trim())
                }
              >
                {uploading ? "Uploading..." : "Upload & Process"}
              </Button>
              <Button
                variant="outline"
                onClick={() => setChunkingModal(null)}
                disabled={uploading}
              >
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Column Description Popover */}
      {columnDescPopover && (
        <>
          <div
            className="fixed inset-0 z-[60]"
            onClick={closeColumnDescPopover}
            onContextMenu={(e) => {
              e.preventDefault();
              closeColumnDescPopover();
            }}
          />
          <div
            className="fixed z-[61] bg-[#1a1a1a] border border-[#464646] rounded-lg shadow-xl p-3 w-[300px]"
            style={{ left: columnDescPopover.x, top: columnDescPopover.y }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-2 gap-2">
              <div className="min-w-0 flex-1">
                <div
                  className="text-xs font-mono text-white truncate"
                  title={columnDescPopover.column.column_name}
                >
                  {columnDescPopover.column.display_name ||
                    columnDescPopover.column.column_name}
                </div>
                <div className="text-[10px] text-[#6b6b6b] uppercase tracking-wide">
                  Column description
                </div>
              </div>
              <button
                type="button"
                onClick={closeColumnDescPopover}
                className="text-[#6b6b6b] hover:text-[#b5b5b5] p-0.5 -mr-1 -mt-1"
                title="Close"
              >
                <svg
                  className="w-3.5 h-3.5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>
            {editingColumnDesc ? (
              <>
                <textarea
                  value={columnDescDraft}
                  onChange={(e) => setColumnDescDraft(e.target.value)}
                  rows={4}
                  autoFocus
                  disabled={savingColumnDesc}
                  placeholder="Describe what this column represents..."
                  className="w-full px-2 py-1.5 border border-[#464646] bg-[#0d0d0d] rounded text-xs text-white placeholder:text-[#6b6b6b] resize-y min-h-[72px] focus:ring-2 focus:ring-[#d93854] focus:border-[#d93854] focus:outline-none disabled:opacity-60 mb-2"
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={handleSaveColumnDescription}
                    disabled={savingColumnDesc}
                    className="flex-1 px-3 py-1.5 text-xs font-medium text-white bg-[#1a1a1a] hover:bg-[#222222] disabled:opacity-50 rounded transition-colors"
                  >
                    {savingColumnDesc ? "Saving..." : "Save"}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEditingColumnDesc(false);
                      setColumnDescDraft(
                        columnDescPopover.column.description || "",
                      );
                    }}
                    disabled={savingColumnDesc}
                    className="px-3 py-1.5 text-xs font-medium text-[#dadada] border border-[#464646] hover:bg-[#1a1a1a] disabled:opacity-50 rounded transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="text-xs text-[#dadada] leading-relaxed whitespace-pre-wrap mb-2 min-h-[40px]">
                  {columnDescPopover.column.description ? (
                    columnDescPopover.column.description
                  ) : (
                    <span className="italic text-[#6b6b6b]">
                      No description yet
                    </span>
                  )}
                </p>
                {!isReadOnly && (
                  <button
                    type="button"
                    onClick={() => {
                      setColumnDescDraft(
                        columnDescPopover.column.description || "",
                      );
                      setEditingColumnDesc(true);
                    }}
                    className="inline-flex items-center gap-1 text-xs font-medium text-[#d93854] hover:text-[#e27588] hover:underline"
                  >
                    <svg
                      className="w-3 h-3"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                      />
                    </svg>
                    {columnDescPopover.column.description
                      ? "Edit description"
                      : "Add description"}
                  </button>
                )}
              </>
            )}
          </div>
        </>
      )}

      {/* Alert Modal */}
      <AlertModal
        isOpen={alertModal.isOpen}
        title={alertModal.title}
        message={alertModal.message}
        variant={alertModal.variant}
        onClose={() =>
          setAlertModal({
            isOpen: false,
            title: "",
            message: "",
            variant: "error",
          })
        }
      />
    </div>
  );
}
