import 'fms_models.dart';

/// The only runtime backend boundary exposed to Control UI pages.
abstract interface class FmsApi {
  Future<List<InventoryLotDto>> listInventory();

  Future<List<MapProjectSummaryDto>> listMapProjects();

  Future<MapProjectOpenDto> openMapProject(String mapName);

  Future<StagedMapSourceDto> stageMapSource(
    String mapName,
    MapSourceUploadDto source,
  );

  Future<MapProjectDraftDto> saveMapDraft(
    MapProjectDraftDto draft, {
    int? expectedRevision,
  });

  Future<void> deleteMapDraft(String mapName);

  Future<MapValidationDto> validateMapDraft(String mapName);

  Future<PublishedMapDto> publishMapDraft(
    String mapName,
    PublishMapDto request,
  );

  Future<OutboundOrderDto> createOutboundOrder(
    OutboundOrderRequestDto request, {
    required String idempotencyKey,
  });

  Future<JobDetailDto> getJob(int jobId);

  Future<JobDetailDto> completeJob(
    int jobId,
    WorkerCompletionDto request, {
    required String idempotencyKey,
  });

  Stream<OperationsEventDto> operationsEvents();

  Future<void> decideEmergency(
    int incidentId,
    EmergencyDecisionDto request, {
    required String idempotencyKey,
  });
}
