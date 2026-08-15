import 'dart:typed_data';

typedef JsonObject = Map<String, Object?>;

Map<String, Object?> _immutableJsonObject(Object? value) => Map.unmodifiable(
  (value as Map<Object?, Object?>).map(
    (key, item) => MapEntry(key as String, item),
  ),
);

List<Map<String, Object?>> _immutableJsonObjects(Object? value) =>
    List.unmodifiable(
      (value as List<Object?>? ?? const []).map(_immutableJsonObject),
    );

DateTime? _optionalDateTime(Object? value) =>
    value == null ? null : DateTime.parse(value as String);

class InventoryLotDto {
  const InventoryLotDto({
    required this.lotId,
    required this.lotCode,
    required this.productCode,
    required this.itemName,
    required this.temperatureZone,
    required this.locationCode,
    required this.expiryDate,
    required this.availableQty,
    required this.reservedQty,
    required this.state,
  });

  factory InventoryLotDto.fromJson(JsonObject json) => InventoryLotDto(
    lotId: json['lot_id'] as int,
    lotCode: json['lot_code'] as String,
    productCode: json['product_code'] as String,
    itemName: json['item_name'] as String?,
    temperatureZone: json['temperature_zone'] as String,
    locationCode: json['location_code'] as String?,
    expiryDate: DateTime.parse(json['expiry_date'] as String),
    availableQty: json['available_qty'] as int,
    reservedQty: json['reserved_qty'] as int,
    state: json['state'] as String,
  );

  final int lotId;
  final String lotCode;
  final String productCode;
  final String? itemName;
  final String temperatureZone;
  final String? locationCode;
  final DateTime expiryDate;
  final int availableQty;
  final int reservedQty;
  final String state;
}

class MapProjectSummaryDto {
  const MapProjectSummaryDto({
    required this.mapName,
    required this.drawingName,
    required this.formatVersion,
    required this.waypointCount,
    required this.laneCount,
    required this.draftRevision,
    required this.hasBuildingYaml,
    required this.updatedAt,
  });

  factory MapProjectSummaryDto.fromJson(JsonObject json) =>
      MapProjectSummaryDto(
        mapName: json['map_name'] as String,
        drawingName: json['drawing_name'] as String?,
        formatVersion: json['format_version'] as int,
        waypointCount: json['waypoint_count'] as int,
        laneCount: json['lane_count'] as int,
        draftRevision: json['draft_revision'] as int,
        hasBuildingYaml: json['has_building_yaml'] as bool,
        updatedAt: DateTime.parse(json['updated_at'] as String),
      );

  final String mapName;
  final String? drawingName;
  final int formatVersion;
  final int waypointCount;
  final int laneCount;
  final int draftRevision;
  final bool hasBuildingYaml;
  final DateTime updatedAt;
}

class MapSourceUploadDto {
  MapSourceUploadDto({
    required this.sourceType,
    required this.fileName,
    required this.mimeType,
    required Uint8List bytes,
  }) : bytes = Uint8List.fromList(bytes);

  final String sourceType;
  final String fileName;
  final String mimeType;
  final Uint8List bytes;
}

class StagedMapSourceDto {
  const StagedMapSourceDto({
    required this.uploadToken,
    required this.sourceType,
    required this.sha256,
    required this.byteSize,
  });

  factory StagedMapSourceDto.fromJson(JsonObject json) => StagedMapSourceDto(
    uploadToken: json['upload_token'] as String,
    sourceType: json['source_type'] as String,
    sha256: json['sha256'] as String,
    byteSize: json['byte_size'] as int,
  );

  final String uploadToken;
  final String sourceType;
  final String sha256;
  final int byteSize;
}

class MapSourceDto {
  const MapSourceDto({
    required this.sourceUuid,
    required this.projectId,
    required this.sourceType,
    required this.sha256,
    required this.byteSize,
  });

  factory MapSourceDto.fromJson(JsonObject json) => MapSourceDto(
    sourceUuid: json['source_uuid'] as String,
    projectId: json['project_id'] as int,
    sourceType: json['source_type'] as String,
    sha256: json['sha256'] as String,
    byteSize: json['byte_size'] as int,
  );

  final String sourceUuid;
  final int projectId;
  final String sourceType;
  final String sha256;
  final int byteSize;
}

class MapProjectDraftDto {
  MapProjectDraftDto({
    required this.mapName,
    required this.formatVersion,
    required this.draftRevision,
    required Map<String, String> sourceUuids,
    required List<JsonObject> waypoints,
    required List<JsonObject> features,
    required this.runtimeProfileHash,
  }) : sourceUuids = Map<String, String>.unmodifiable(sourceUuids),
       waypoints = List<JsonObject>.unmodifiable(
         waypoints.map(Map<String, Object?>.unmodifiable),
       ),
       features = List<JsonObject>.unmodifiable(
         features.map(Map<String, Object?>.unmodifiable),
       );

  factory MapProjectDraftDto.fromJson(JsonObject json) => MapProjectDraftDto(
    mapName: json['map_name'] as String,
    formatVersion: json['format_version'] as int,
    draftRevision: json['draft_revision'] as int,
    sourceUuids: (json['source_uuids'] as Map<Object?, Object?>? ?? const {})
        .map((key, value) => MapEntry(key as String, value as String)),
    waypoints: _immutableJsonObjects(json['waypoints']),
    features: _immutableJsonObjects(json['features']),
    runtimeProfileHash: json['runtime_profile_hash'] as String,
  );

  final String mapName;
  final int formatVersion;
  final int draftRevision;
  final Map<String, String> sourceUuids;
  final List<JsonObject> waypoints;
  final List<JsonObject> features;
  final String runtimeProfileHash;

  JsonObject toJson() => {
    'map_name': mapName,
    'format_version': formatVersion,
    'draft_revision': draftRevision,
    'source_uuids': sourceUuids,
    'waypoints': waypoints,
    'features': features,
    'runtime_profile_hash': runtimeProfileHash,
  };
}

class MapProjectOpenDto {
  const MapProjectOpenDto({
    required this.draft,
    required this.openExisting,
    required this.activeRevision,
  });

  factory MapProjectOpenDto.fromJson(JsonObject json) => MapProjectOpenDto(
    draft: MapProjectDraftDto.fromJson(_immutableJsonObject(json['draft'])),
    openExisting: json['open_existing'] as bool,
    activeRevision: json['active_revision'] as String?,
  );

  final MapProjectDraftDto draft;
  final bool openExisting;
  final String? activeRevision;
}

class MapValidationDto {
  MapValidationDto({required this.valid, required List<String> errorCodes})
    : errorCodes = List.unmodifiable(errorCodes);

  factory MapValidationDto.fromJson(JsonObject json) => MapValidationDto(
    valid: json['valid'] as bool,
    errorCodes: List<String>.from(
      json['error_codes'] as List<Object?>? ??
          json['errors'] as List<Object?>? ??
          const [],
    ),
  );

  final bool valid;
  final List<String> errorCodes;
}

class PublishMapDto {
  const PublishMapDto({
    required this.expectedDraftRevision,
    required this.publishedBy,
  });

  final int expectedDraftRevision;
  final String publishedBy;

  JsonObject toJson() => {
    'expected_draft_revision': expectedDraftRevision,
    'published_by': publishedBy,
  };
}

class PublishedMapDto {
  PublishedMapDto({
    required this.mapName,
    required this.mapRevision,
    required this.draftRevision,
    required JsonObject manifest,
  }) : manifest = Map.unmodifiable(manifest);

  factory PublishedMapDto.fromJson(JsonObject json) => PublishedMapDto(
    mapName: json['map_name'] as String,
    mapRevision: json['map_revision'] as String,
    draftRevision: json['draft_revision'] as int,
    manifest: _immutableJsonObject(json['manifest']),
  );

  final String mapName;
  final String mapRevision;
  final int draftRevision;
  final JsonObject manifest;
}

class OutboundOrderLineDto {
  const OutboundOrderLineDto({
    required this.productCode,
    required this.quantity,
  });

  final String productCode;
  final int quantity;

  JsonObject toJson() => {'product_code': productCode, 'quantity': quantity};
}

class OutboundOrderRequestDto {
  OutboundOrderRequestDto({
    required this.externalReference,
    required this.requester,
    required this.priority,
    required this.allowPartialFulfillment,
    required List<OutboundOrderLineDto> lines,
  }) : lines = List.unmodifiable(lines);

  final String? externalReference;
  final String requester;
  final String priority;
  final bool allowPartialFulfillment;
  final List<OutboundOrderLineDto> lines;

  JsonObject toJson() => {
    'external_reference': externalReference,
    'requested_by': requester,
    'priority': priority,
    'allow_partial_fulfillment': allowPartialFulfillment,
    'items': lines.map((line) => line.toJson()).toList(growable: false),
  };
}

class OutboundOrderDto {
  const OutboundOrderDto({
    required this.jobId,
    required this.jobCode,
    required this.externalReference,
    required this.state,
    required this.requestedQuantity,
    required this.fulfillableQuantity,
    required this.outstandingQuantity,
  });

  factory OutboundOrderDto.fromJson(JsonObject json) => OutboundOrderDto(
    jobId: json['job_id'] as int,
    jobCode: json['job_code'] as String,
    externalReference: json['external_reference'] as String?,
    state: json['state'] as String,
    requestedQuantity: json['requested_quantity'] as int,
    fulfillableQuantity: json['fulfillable_quantity'] as int,
    outstandingQuantity: json['outstanding_quantity'] as int,
  );

  final int jobId;
  final String jobCode;
  final String? externalReference;
  final String state;
  final int requestedQuantity;
  final int fulfillableQuantity;
  final int outstandingQuantity;
}

class JobDetailDto {
  JobDetailDto({
    required this.jobId,
    required this.jobCode,
    required this.operationType,
    required this.priority,
    required this.state,
    required this.requestedBy,
    required this.externalReference,
    required this.sourceLocationId,
    required this.destinationLocationId,
    required this.dueAt,
    required JsonObject context,
    required this.createdAt,
    required List<JsonObject> steps,
  }) : context = Map<String, Object?>.unmodifiable(context),
       steps = List<JsonObject>.unmodifiable(
         steps.map(Map<String, Object?>.unmodifiable),
       );

  factory JobDetailDto.fromJson(JsonObject json) => JobDetailDto(
    jobId: json['job_id'] as int,
    jobCode: json['job_code'] as String,
    operationType: json['operation_type'] as String,
    priority: json['priority'] as String,
    state: json['state'] as String,
    requestedBy: json['requested_by'] as String?,
    externalReference: json['external_reference'] as String?,
    sourceLocationId: json['source_location_id'] as int?,
    destinationLocationId: json['destination_location_id'] as int?,
    dueAt: _optionalDateTime(json['due_at']),
    context: _immutableJsonObject(json['context'] ?? const <String, Object?>{}),
    createdAt: DateTime.parse(json['created_at'] as String),
    steps: _immutableJsonObjects(json['steps']),
  );

  final int jobId;
  final String jobCode;
  final String operationType;
  final String priority;
  final String state;
  final String? requestedBy;
  final String? externalReference;
  final int? sourceLocationId;
  final int? destinationLocationId;
  final DateTime? dueAt;
  final JsonObject context;
  final DateTime createdAt;
  final List<JsonObject> steps;
}

class WorkerCompletionDto {
  WorkerCompletionDto({
    required this.workerId,
    required this.completionNote,
    required List<int> acknowledgedManualItemIds,
  }) : acknowledgedManualItemIds = List.unmodifiable(acknowledgedManualItemIds);

  final String workerId;
  final String? completionNote;
  final List<int> acknowledgedManualItemIds;

  JsonObject toJson() => {
    'worker_id': workerId,
    'completion_note': completionNote,
    'acknowledged_manual_item_ids': acknowledgedManualItemIds,
  };
}

class OperationsEventDto {
  OperationsEventDto({
    required this.eventId,
    required this.eventUuid,
    required this.occurredAt,
    required this.actorWorkerId,
    required this.deviceId,
    required this.jobId,
    required this.jobStepId,
    required this.incidentId,
    required this.severity,
    required this.category,
    required this.eventType,
    required this.message,
    required JsonObject? payload,
  }) : payload = payload == null ? null : Map.unmodifiable(payload);

  factory OperationsEventDto.fromJson(JsonObject json) => OperationsEventDto(
    eventId: json['event_id'] as int,
    eventUuid: json['event_uuid'] as String,
    occurredAt: DateTime.parse(json['occurred_at'] as String),
    actorWorkerId: json['actor_worker_id'] as String?,
    deviceId: json['device_id'] as String?,
    jobId: json['job_id'] as int?,
    jobStepId: json['job_step_id'] as int?,
    incidentId: json['incident_id'] as int?,
    severity: json['severity'] as String,
    category: json['category'] as String,
    eventType: json['event_type'] as String,
    message: json['message'] as String?,
    payload: json['payload'] == null
        ? null
        : _immutableJsonObject(json['payload']),
  );

  final int eventId;
  final String eventUuid;
  final DateTime occurredAt;
  final String? actorWorkerId;
  final String? deviceId;
  final int? jobId;
  final int? jobStepId;
  final int? incidentId;
  final String severity;
  final String category;
  final String eventType;
  final String? message;
  final JsonObject? payload;
}

enum EmergencyDecision { raiseAlarm, continueWork }

extension on EmergencyDecision {
  String get wireValue => switch (this) {
    EmergencyDecision.raiseAlarm => 'RAISE_ALARM',
    EmergencyDecision.continueWork => 'CONTINUE_WORK',
  };
}

class EmergencyDecisionDto {
  const EmergencyDecisionDto({
    required this.workerId,
    required this.decision,
    required this.reason,
  });

  final String workerId;
  final EmergencyDecision decision;
  final String reason;

  JsonObject toJson() => {
    'worker_id': workerId,
    'decision': decision.wireValue,
    'reason': reason,
  };
}
