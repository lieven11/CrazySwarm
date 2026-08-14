# WP-57 through WP-61 implementation manifest v1

- Base commit: `07f4718dfdbfbb2bc2d7c7bdeb49a6558dee6597`.
- Accepted design: base `2096bac6a01dd437ff5f909bc63bd3b012b30927b7d270aa3f9c4644049f8c6f`, R2 `e1be5e88fa91c510eb5612ee1b30d35347df53008e4fd7d563f044cbd6c67b5c`, corrected R3 `6f46645b39ee279b87bede0c530e4bc77fab138552cdcd8498837d02ed23deff`.
- Exact staged implementation patch SHA-256: `3c9cd9bf0e65e35c72e50db74015b0e8429800d9cf7c396291b27d009568d735`.
- Payload rule: the hash and table cover the staged implementation before this mechanical manifest and any later independent-verification record. No deleted files are present.
- Author checks: focused Python lint and 13 production/component tests passed; the earlier broader packet sweep passed 54 tests before the final runtime-randomization clarification.
- Environment limitation: the UI dependency installation was already interrupted; UI lint/browser serving could not run because local executables/transitives were missing. This is retained as a verifier-visible limitation, not reported as a pass.
- Hardware boundary: real-aircraft execution remains literal `NOT_RUN`; only fail-closed handoff readiness is claimed.

| Change | Path | Base/preimage SHA-256 | Implemented/postimage SHA-256 |
|---|---|---|---|
| `M` | `config/qualification/reality-physical-plan-v1.json` | `04e950f5d2dea29a909bdc6639290b42caa6f95f1a9311737415bf7c742d12b1` | `4574faa4c1140ae27c412cfd8dfb9f1f74c40cd32f032b9b15a5be3645582db3` |
| `M` | `docs/project/WORKFLOW_AND_REQUIREMENTS.md` | `b8972dfc2c74256adf268c672ae82a5bf700c43ab65d68d98a3aca88e3973183` | `910fb7849c679152c58848550261fe79abaf6bd2e3a23286c973943945ac5bff` |
| `M` | `docs/work-packages/ACTIVE.md` | `a95703c46129fd3ad523e7c56873f672ec8ac74b91944e51729a972365fc6927` | `0632dcefa9e7801bc284d1e84825e862aeae0cedbc4934af5323175a4b5f5693` |
| `M` | `missions/campaigns/sim/cases/basic-flight-and-route-following/1d-cases-v1.yaml` | `964aa81d6a112103365bc8842b2cf55d1ea9a5713ad521bc543920363e0ab617` | `e6a541f7173e71b489c97340ff0612219b95e3d92aaf31b5ce787fe40cb081eb` |
| `M` | `missions/campaigns/sim/qualification/selective-submission-registry-v1.json` | `e99803b2c2bdf6d4e3cf398da90d4a283b39b78051368f04c74186e1a81aa5d5` | `9e79f82ec20aec3ee17b0596d123edb99cd4c4e93dabe33d17a81fc983a950cd` |
| `M` | `missions/campaigns/sim/qualification/wp52-56-r7-implementation-reconciliation-v1.json` | `cbe12d66444e61f818b05e374103b56ba5a7b504ca7def5a238dfb1b0429e85f` | `7cbf5b454a991d59496dc76bc03a2be9b82a20a86ed4c4ad47e8d32f382a6fc2` |
| `M` | `missions/campaigns/sim/submissions/admission-records-v1.yaml` | `c7ddb86102c63693d18c031e9498506df551b4eac7310b09d7c1a9e9b26d67dc` | `c24a888659916d3281ef02ffe55b7a597d6a3ea34bd8bcac1327e5e8c224864c` |
| `M` | `missions/campaigns/sim/submissions/case-submissions-v1.yaml` | `51e16625e636b983fd54fe7f92599f23eece4f8b7bd938aef59644c19834acbd` | `792a52aae56e9f84145419e8462fbfc471b1b8ac3c1bd2913af3a720394a72ab` |
| `A` | `missions/library/one_drone/online_obstacle_replan/mission.py` | `ABSENT` | `d20a7a6d8cfda64e1a931bb78d7bde073d7940eb61995a290336a77835feb89b` |
| `M` | `scripts/campaign_case_specs.py` | `5c02700b2638af8ae57223d6ee24418e592a56913ac6588a4ca24f3228d48af9` | `c3fdacf0d41ddaf1593b10c27b718b2b5e0346285d13b89b9fa9e010b72010c4` |
| `M` | `scripts/generate_campaign_catalog.py` | `715afda601bb517482cc868b5ae91b0e8a61e434702f31049fc3f39c2c5167a0` | `f9a5f3b6dfae1ed24c139124c7faadc097ed24d0d28ecaf45bb49605121c255a` |
| `M` | `scripts/generate_submission_registry.py` | `ee28fcbd08fa4221a100e5224219b217fce85b5aae2bdd68494197527d0b6c81` | `e46ea834b7e1eff640b3489b82d891253a2adde3c186d7dcb054c84d44a4804b` |
| `M` | `scripts/qualify_submission_registry.py` | `309f6078dd5f412f75a458de11715cdb4b429053a3d1a4c87edc0dc58728ee62` | `2f02e17bf33f334234e07af39aab683245f9ba4d97e94686e6f004292cf61538` |
| `M` | `scripts/qualify_submission_registry_r6.py` | `b76bbfd29a0b5f66b27ec0edbbe55ab9d8cb2d5658b76cd8093a5e9b8d01274b` | `a5e31a749045f9b59c7e60b3d2d23205b6118220a7ed57dc39967a14f9b2f797` |
| `M` | `scripts/reconcile_wp52_56_r7_implementation.py` | `a8dc40466f897ef6e71bf176f9bed97cd33a3707df58e674cd291a73833853b9` | `da858a778dcc9ce6d255b443c52a064e3e0bdf256d2048133bbdf031414bc714` |
| `M` | `src/crazyswarm_app/api/app.py` | `7015952b033fcecaa1e36a9777ecc6c1373549fd96c3e4cc0a610a8e6d79a718` | `3335eec9f4f8dd04fdba9ebb02541af23c1c61fcdbdf122ec459eeeea5455ea0` |
| `M` | `src/crazyswarm_app/api/runtime.py` | `b257d952d3ac15bed827c862c7e9891ab005f31a18ca438474cc8c8e93064072` | `fba2d6ccd5479957ac9d1107a77f1248b5f47004a3c0c562f665299238268458` |
| `M` | `src/crazyswarm_app/campaign/analyzer.py` | `c2e62b8411dc9f9938208e75adb3d5be7663263e57d0c9cb7ab4cda4c07c540a` | `302479e9ec602da3711fad6dfb2880d08b4e2d538de591e858108955c5f9aa81` |
| `M` | `src/crazyswarm_app/campaign/api_models.py` | `06a8620e2c08512ab5e8b0d9d060bd29dc51fd0e358400a9dee0f6482165c39f` | `469855915a16a038a53fc7d8029803b291a8820b3ee4b4c4df2d155651219b02` |
| `M` | `src/crazyswarm_app/campaign/catalog.py` | `2111911ac0c36602cb660e1e01dc61f6fae10e691c7c4795a1270e577e974b2c` | `b4a93deb2cc347b83cc908111f0d0a89849daaad717a19ebbdfbd55713758c0c` |
| `M` | `src/crazyswarm_app/campaign/execution_head.py` | `a6510c17f13a0f6d8b82ef450c2442b3271b32046932d6c6a7de245dba43e5bc` | `bcbb0feca7690458dd592a577ee7e3306dbc5574a6d6a6939bc842a3289b42e1` |
| `M` | `src/crazyswarm_app/campaign/models.py` | `31c3b5067972298b9dbd4a4dc026ff3b48de96685b253a9b22d48293eb71fdf0` | `ac2f08d38ac18a7664e59ee7ca5b23e0860f22d4bbd564306e03ad28b7ea9a9d` |
| `A` | `src/crazyswarm_app/campaign/perception.py` | `ABSENT` | `e8b39b2f753c5550b41b52c4eb1ae58e48ab8449d563a08498443978431fb565` |
| `A` | `src/crazyswarm_app/campaign/physical_truth.py` | `ABSENT` | `01385a77ea5dc01e555eb90c5254e4dc1555991a1af26e2b185be4ee1fe4f194` |
| `M` | `src/crazyswarm_app/campaign/planner.py` | `4bed265f082def6902b6c08b86302285dfc93d45b4c46877e5fb5419866ce23c` | `3f50488f604771012e1c57fefff0f60bcf246225eb6e54818f9ecf078ed9618d` |
| `M` | `src/crazyswarm_app/campaign/replanning.py` | `8a80ff02979979affe6dc1cee9d4d0550430473d36de0a3fb5d1abffe0f054e9` | `617812ccb4d8417f18c59dd573522ddf55a06c640694ce00231a701cd4fbd4b4` |
| `A` | `src/crazyswarm_app/campaign/route_horizon.py` | `ABSENT` | `e962f96c2214261bfc6510b6e0b537286a1e0185b2f47b67fff19ec53ad8054a` |
| `M` | `src/crazyswarm_app/campaign/runtime_executor.py` | `eff68869fcc5943adbc5d3b1e258f5304f213417121d9207f312b7d2bd5a3e38` | `01147f73f10f499c590a17536133cf0d0fb68cbafc014b3479e0f6f48c5db5ce` |
| `M` | `src/crazyswarm_app/campaign/service.py` | `3a9e3047ba587b0545413fb0b3564a0d774b54fd157e394fc9817e074bc23a00` | `6a388724ec51ceab590f700daf29bf47c425b2fd0eb33c5470f9d6f4c580c43c` |
| `M` | `src/crazyswarm_app/campaign/submission_measurement.py` | `00a846c86d637c73e36fb54528e76910b7696b2af30ad3302465bed9d3fc36bb` | `41629de8f64dc2a1c0eaa61f9c805f1f63bd163338f4de24844fb169ed207672` |
| `M` | `src/crazyswarm_app/campaign/submissions.py` | `9b31d64b04037420b7c8e68420d2db44d4d09d9b8e3fcec1903c4dfee150f919` | `c5ea151268581951e356f0fe814d8a30de107f94d84fe42ffbfeec42bb81333f` |
| `M` | `src/crazyswarm_app/campaign/trajectory.py` | `39b320d3a93064a751203b104ac64d4f013369e5b97df8e9b1b90d911c07dc08` | `201cdce13cb76107c8088e92e5bc01365bfd29baf271871fa0aed1262577dffd` |
| `M` | `src/crazyswarm_app/missions/base.py` | `887e02db596015f4e27ac4d75476408d31c760c997860101b9243ef7ca371702` | `7ae157b233bafdb0507226d93cdaa093d48f7aad13b9054726cf98c01f89a5a1` |
| `M` | `src/crazyswarm_app/simulation/sensors.py` | `b49dd4a9a594b25201b89c3e45300e8299a8d9fe9cd667a087f1e989bc7fcba6` | `138940f31305e7e5e5342047d2c4f62e63849732490f012b2e767fe5a8fdc7c2` |
| `M` | `src/crazyswarm_app/simulation/vehicle.py` | `c40f660b35e12b5cc01c5aa76d02f9afc2b7fc28c9b1eb6948963518f16c71e3` | `6187fc02fb38434ebeff3922377d81c0ec26f1956dfe71ac25357acc2b27c0cf` |
| `M` | `src/crazyswarm_app/simulation/world.py` | `5a9c4df5b8b00a4e63835bcede4b695e3cca760d4fed7965eaa95aa781d13c5d` | `533fa4e98229ed150a8ad29232b515546b20c5fc35f19ecfac1e93b0d5323d99` |
| `A` | `src/crazyswarm_app/twin/calibration.py` | `ABSENT` | `874327c22a05ace974b5ea030b9620f5b22541cea559120cc772eeb9410649b6` |
| `M` | `src/crazyswarm_app/twin/coordinator.py` | `219894404160f2c726f402b3f92151b9c6702f906d3ea2c5f84ea004b9df6cbf` | `ce233058b7e73e65f72b7a901566c3c5eccc017f643db0bf8abd872aaf6a8966` |
| `A` | `src/crazyswarm_app/twin/curriculum.py` | `ABSENT` | `b14fcce7ec8b364fb5595a1939143e481e07f2b315cd69a10e1963293ac4d2d8` |
| `A` | `src/crazyswarm_app/twin/ingestion.py` | `ABSENT` | `4aac3e897f17ff3a88c6870bc8e2d6c50c6e57a11dcc319456142cb048a22228` |
| `M` | `src/crazyswarm_app/twin/models.py` | `4f5de2f3fbd8f4f769cfab34963ecb7e424e36543e0998559f99081b5c37d3d1` | `b69cbc4e17a634fb0190ef526ae264b27ca3994fcf8c8d0a1543624cd401561f` |
| `A` | `src/crazyswarm_app/twin/physical_handoff.py` | `ABSENT` | `052618a55b599a1fb1daecb15026ca8b9e8c0c9e040aa9be324eba8653f44396` |
| `A` | `src/crazyswarm_app/twin/pipeline.py` | `ABSENT` | `7e7d0cef1e6a14a5d56cfa182709fd375b0ba84563516f6ca5ea4103bab9f565` |
| `A` | `src/crazyswarm_app/twin/replay.py` | `ABSENT` | `2f7cdcaf278f5861d3a655e58ca3c0b6263e6be8dc7e68eb001d27634cf43f8d` |
| `A` | `src/crazyswarm_app/twin/storage.py` | `ABSENT` | `915607e1a32ad8f21dc3dc976ede71f1451b9f356e82045c249ffc767a812ac5` |
| `M` | `tests/api/test_campaign.py` | `4f5eb0b14142b7d911a887da2f13368281489fd9c3b9eebb61212daa7e2f87a8` | `9ffecac8dcbcc4a98ddfe3c27455b68afe27d559f40f93f084cf61230b28e911` |
| `A` | `tests/api/test_twin.py` | `ABSENT` | `2707ffb7354df38318129f92574a998ac7eff887755ea60157eabcd202a2d8d2` |
| `A` | `tests/campaign/test_adaptive_motion_cutover.py` | `ABSENT` | `7fcb42e9a04da2568befe79ac8559da99c367865321f93b4d780f7f12fdad2ac` |
| `M` | `tests/campaign/test_campaign_execution.py` | `f1fd0ba50a3671a5a6b8bb526f06c6bfc4ae8ae51df1c0c6030304ae51ff91ad` | `0af8b197e2c4d817fd419f1ad17df4273569030da476d3552514986db5f1968f` |
| `M` | `tests/campaign/test_campaign_lab.py` | `c7d8b414e8613fc84d85b777ffb17100d31c5e916a0cc74b40ceba23c893cdc3` | `e9131948f284c267d3863c1313ab9498b5a4ec9c36a36a6a1974b82ff332756b` |
| `A` | `tests/campaign/test_changed_world_safety_monitor.py` | `ABSENT` | `89d570e1dd8484a90ef9e8387dbfebdcb727070c4c2b691fea58d3a95aa53e7f` |
| `A` | `tests/campaign/test_dynamic_perception_replanning.py` | `ABSENT` | `a7c048277bbb3b3c997290e50d904f74d75bff02034681b406eb71e9f1281919` |
| `M` | `tests/campaign/test_dynamic_replanning.py` | `d0197febfc23dea476ea2a101c49702c7ba1b4de6e8bacfd7aa08e751bb7c34d` | `6bddbef59f8e7c00e99f324d72d8fe3f2532c74fc833240cebaeb5694d1921cc` |
| `A` | `tests/campaign/test_motion_production_qualification.py` | `ABSENT` | `966f0c0911a7c7356946c12b8173e9111836d1371f69b9ce4fd2651cb1f49e01` |
| `A` | `tests/campaign/test_motion_quality_contract.py` | `ABSENT` | `c5235fd391b9cf224d9ef52979750ed63c9071ce3d43bda655ba69da1ff3be91` |
| `A` | `tests/campaign/test_one_drone_execution_head.py` | `ABSENT` | `e7c5d6fa4e1e18cf6c1bcf4afca27d44641f41122493558831353acab4c8cf01` |
| `A` | `tests/campaign/test_perception_contract.py` | `ABSENT` | `34d25960102bd84dc8a51191f3b3a6076e0c97d0fb7c48b51f05c1a6f96e770a` |
| `A` | `tests/campaign/test_physical_truth.py` | `ABSENT` | `b0c00df29fc4a61ad10ed24f16293317de351966ec831b3a612a160c597e78ff` |
| `A` | `tests/campaign/test_reality_mission_e2e.py` | `ABSENT` | `94028f702950e3f2c24c4924dac461f2d6974da951463a4b0c8d46264c376df2` |
| `A` | `tests/campaign/test_route_horizon.py` | `ABSENT` | `0c55bd702bab954dd4fb9cbb6b0430f09fe80858c7fa2179e03f2337ebc3e356` |
| `M` | `tests/campaign/test_submission_runtime_qualification.py` | `1418efec0947dd9a86551c28bbda23009ba085e064f31eaf20f548ff76566bf8` | `7a453489120bdf39bea6ea3f5ebe386298ca8e0fa84201a6d84755a24a61b513` |
| `M` | `tests/campaign/test_submissions.py` | `456f9631194ab504ec40d3807f861003a9fe9ff22fefcc29b2a74efb90cf68a3` | `a4408abb1be66d3b7eb7dae99dcb4a634b78dcbbe9f46ae1c4dadd4b86cd3781` |
| `A` | `tests/campaign/test_whole_route_motion.py` | `ABSENT` | `95633169bd692f69075f5e1c1ec9824b297d791f42c6746f460b09e3c843c4cd` |
| `A` | `tests/campaign/test_whole_route_smoother.py` | `ABSENT` | `b81e5e3391570cfa60af091be20b25573596647533573bd5f76ff058540e4614` |
| `A` | `tests/campaign/test_wp58_baseline_oracle.py` | `ABSENT` | `83898c58736b24b8b454a75606c5f84d8c5187d45230a54d89ef74b6ed9c94cc` |
| `A` | `tests/simulation/test_dynamic_obstacle_sensor.py` | `ABSENT` | `cdf2115ec3c0a535cb8a5507a52d50ce901c600d0d21005f3af221d6783cab7a` |
| `A` | `tests/simulation/test_motor_physical_truth.py` | `ABSENT` | `47364144acca753d71a9b0c2171682bd61bef6ddc56e475e75d53127019def0e` |
| `M` | `tests/simulation/test_vehicle.py` | `cecf5ad7173ad9d1dff0467a9983f900d56a7e6d5cad49a4ba0bd3712ea8384f` | `25a9b5a4dd13ae4aae9dbff33a325b77e8452a4b9218b2daf0848bef6322dc91` |
| `A` | `tests/twin/test_calibration.py` | `ABSENT` | `d5b755fbad398bbc911bce61247f13cef22af3d833ac35b58c5d7d54bd00f937` |
| `A` | `tests/twin/test_curriculum.py` | `ABSENT` | `0ada38ec6e626dce7c6860ae270e3ee01eef9e437ddcc1aa72edda2c0f77dea4` |
| `A` | `tests/twin/test_ingestion.py` | `ABSENT` | `32908909f9d7df0f2f74ee6bf8763bbff6d5238b5d87c106ee67092c4eed686c` |
| `A` | `tests/twin/test_persistence.py` | `ABSENT` | `f01be64c43e8807923a84bb73d90492a33f00da89dfcf27a10f51a5833af8280` |
| `A` | `tests/twin/test_physical_handoff.py` | `ABSENT` | `09fd720b521cf7d76bcd5bed438d3df92081ff0a64b68466db616634abc4234a` |
| `A` | `tests/twin/test_replay.py` | `ABSENT` | `ab048fcafe999b57c17c27f88a0334961007244b078b1413d7519ca20f4e448e` |
| `A` | `tests/twin/test_storage.py` | `ABSENT` | `56de4fdc1468c4c741db29ac7ee934e5db83a680c69c804da5eca727705b1c1e` |
| `A` | `tests/twin/test_twin_pipeline_e2e.py` | `ABSENT` | `da5141b8abb8c0d4ad90ada4f6e40a76a40ef5e75f5e87577cb17516be2089c0` |
| `M` | `ui/app/components/CampaignLab.tsx` | `3f0f39d058f79b3f088166c054c99bc5f79fb514d62691564429ca95a6613c11` | `c8a2bc0ba90e334e2deca2d5adadfc24fc77799f87df17d3b7170f1038673676` |
| `M` | `ui/app/components/ControlCenter.tsx` | `9904f9462ac05f2924df48e54875089434a36814bbfb10d030baeb68ccaaa0fb` | `6a1e18b1dcf1a00fb558e8bcf164d3e11e43db6ac66af1cb3b297b7e4a16948f` |
| `M` | `ui/app/components/RoomScene.tsx` | `63c65e5b852cef9e7913426cec4c7a52b439066374e86bb9da1524429b3a8d05` | `4ddefcb93676ff90a6b79adf547dd344ade311197294577862805920d60afc82` |
| `M` | `ui/app/components/TelemetryDock.tsx` | `8597b063d755bcc1a26f7617ed3b9abc57430fcf717165b87814eb31cde5baf7` | `549b86a5e566a95edbd2f12c3b53a853a1c425843cfcb7a4dc4f3bafaaac58d2` |
| `M` | `ui/app/globals.css` | `38e9e8d533591aa08d3458e69fcb2845b07fec472ea66536a23984a32a99ccb1` | `0e8c7a744d655ed8739668032e04647a7625453ac09fea4e6d41ed20c6183615` |
| `M` | `ui/app/lib/api.ts` | `7feb12cade8a83f426c1b2017a45ec4d33c28d1a8d0fac366de426ba1d7be29d` | `b6dc71dfb2a6de15223203f45a91f037422da331eb7e6343e4ba632b61a5878c` |
| `M` | `ui/app/lib/models.ts` | `be9c09ea870a4bcb00320b54bdc2a2b4dad46a8dc92490b38e28e28d2d3c3622` | `6d0f68eea6a27e01c581292c94d3ddff39d7a8091044a5d237ec2ab040639e7a` |
| `A` | `ui/tests/campaign-motion-quality.test.tsx` | `ABSENT` | `3b179acbc019dafc889f1a0ac506b1cbf79e211e9b58a9a7f9df6a70adb0bd1b` |
| `A` | `ui/tests/campaign-replan-timeline.test.tsx` | `ABSENT` | `b4bb1ff1edd34274c99a4327bbf041d205511f823a55c20b893ff772f7ae2b18` |
| `A` | `ui/tests/motor-truth.test.tsx` | `ABSENT` | `ec44e29ee944a4c4e3220f307168bd381bb4a1962c9732a1e2f9447a415d084a` |
| `A` | `ui/tests/twin-session.test.tsx` | `ABSENT` | `abbcafa856eec377b05a753f1496a62e69feeab916489afe03512806858a5f35` |

## Sole implementation-fix overlay

- Trigger: independent implementation review P1 for WP-59A/B/E future-truth exclusion.
- Scope: only the operator-identified obstacle clairvoyance gap; the other verifier findings are retained rather than broadened into this fix pass.
- Exact overlay patch SHA-256: `a9dd5636b86b29e8c21a93d44e3554cc3d4c6491fb90ffe6ba29a810afdb340b`.
- Behavior: environment-change events are removed from the initial planner input and case identity, remain bound by the separate execution-semantics identity, and a perturbation proves that changing hidden geometry and timing changes execution identity but not initial plan identity.
- Focused evidence: ruff passed; four sensor/E2E tests passed. Catalog and registry were regenerated. The catalog generator has no `--check` option, so the attempted unsupported flag is retained as a command limitation rather than a passing check.

| Path | Initial implementation SHA-256 | Fix postimage SHA-256 |
|---|---|---|
| `missions/campaigns/sim/submissions/admission-records-v1.yaml` | `c24a888659916d3281ef02ffe55b7a597d6a3ea34bd8bcac1327e5e8c224864c` | `9bca1b3a0065645aae2df66f46a229cc80b5c7393e94107b381009f73c9d48b8` |
| `missions/campaigns/sim/submissions/case-submissions-v1.yaml` | `792a52aae56e9f84145419e8462fbfc471b1b8ac3c1bd2913af3a720394a72ab` | `b4549b2e4da9d3b7e6cfd2683e6103e303ba6c2d4c935139dcf883a60a6d3f34` |
| `src/crazyswarm_app/campaign/models.py` | `ac2f08d38ac18a7664e59ee7ca5b23e0860f22d4bbd564306e03ad28b7ea9a9d` | `6c17bddea10a57baa502f8fe86a01e59813b9a6b1a911a21b561d6d3f0c77f32` |
| `src/crazyswarm_app/campaign/planner.py` | `3f50488f604771012e1c57fefff0f60bcf246225eb6e54818f9ecf078ed9618d` | `cb9a3298b165936d942ac879e94a72ed601e3d36e51b1a3896672e1ce6eea769` |
| `tests/simulation/test_dynamic_obstacle_sensor.py` | `cdf2115ec3c0a535cb8a5507a52d50ce901c600d0d21005f3af221d6783cab7a` | `233b15f7612b2f68e79046e4c661b5df91d158a43d7a28360fe696a5c2d2aad9` |
