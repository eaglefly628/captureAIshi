import renderdoc as rd
import rdtest

class VK_Resource_Usage(rdtest.TestCase):
    demos_test_name = 'VK_Simple_Triangle'
    resourceUsages = {}

    def check_resource_usage(self, res: rd.ResourceDescription, expectedUsages=[]):
        usages = self.resourceUsages[res.resourceId]
        if len(usages) != len(expectedUsages):
            raise rdtest.TestFailureException(f"'{res.name}' {res.resourceId} Incorrect resource usages count expected:{len(expectedUsages)} actual:{len(usages)}")
        for i, u in enumerate(usages):
            eid, usage = expectedUsages[i]
            if u.usage != usage:
                raise rdtest.TestFailureException(f"'{res.name}' {res.resourceId} EID:{u.eventId} Incorrect resource usage expected:{usage.name} actual:{u.usage.name}")
            if u.eventId != eid:
                raise rdtest.TestFailureException(f"'{res.name}' {res.resourceId} usage:{u.usage.name} Incorrect resource usage EID expected:{eid} actual:{u.eventId}")

    def check_capture(self):
        # Cache the resource usage before running any replay i.e. without calling SetFrameEvent
        resources = self.controller.GetResources()
        for res in resources:
            self.resourceUsages[res.resourceId] = self.controller.GetUsage(res.resourceId)

        action = self.find_action("Draw")
        self.controller.SetFrameEvent(action.eventId, False)
        swapImage = self.controller.GetPipelineState().GetOutputTargets()[0].resource
        textures = self.controller.GetTextures()

        for res in self.controller.GetResources():
            expectedUsage = []
            if res.type == rd.ResourceType.Device:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            elif res.type == rd.ResourceType.Queue:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            elif res.type == rd.ResourceType.Pool:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            elif res.type == rd.ResourceType.SwapchainImage:
                # the swap chain image has usage, anything else does not
                if res.resourceId == swapImage:
                    expectedUsage = [(6,rd.ResourceUsage.Barrier), (6,rd.ResourceUsage.Discard), (7,rd.ResourceUsage.Clear), (17,rd.ResourceUsage.ColorTarget), (19,rd.ResourceUsage.Barrier)]
                else:
                    expectedUsage = []
            elif res.type == rd.ResourceType.RenderPass:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            elif res.type == rd.ResourceType.Sync:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            elif res.type == rd.ResourceType.View:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            elif res.type == rd.ResourceType.Memory:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            elif res.type == rd.ResourceType.ShaderBinding:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            elif res.type == rd.ResourceType.Shader:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            elif res.type == rd.ResourceType.PipelineState:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            elif res.type == rd.ResourceType.Buffer:
                expectedUsage = [(17,rd.ResourceUsage.VertexBuffer)]
            elif res.type == rd.ResourceType.Texture:
                desc = [x for x in textures if x.resourceId == res.resourceId][0]
                # Hard coded distinguish by the format of the texture
                if desc.format.compByteWidth == 2 and desc.format.compCount == 4 and desc.format.compType == rd.CompType.Float:
                    expectedUsage = [(10,rd.ResourceUsage.Barrier), (10,rd.ResourceUsage.Discard), (11,rd.ResourceUsage.Clear)]
                elif desc.format.compByteWidth == 4 and desc.format.compCount == 4 and desc.format.compType == rd.CompType.Float:
                    expectedUsage = [(8,rd.ResourceUsage.Barrier), (8,rd.ResourceUsage.Discard), (9,rd.ResourceUsage.Clear)]
            elif res.type == rd.ResourceType.CommandBuffer:
                expectedUsage = [(0,rd.ResourceUsage.Unused)]
            else:
                raise rdtest.TestFailureException(f"'{res.name}' {res.resourceId} Unexpected resource type {res.type.name}")
            rdtest.log.print(f"Resource '{res.name}' type:{res.type.name} {res.resourceId} usages:{len(self.controller.GetUsage(res.resourceId))} expectedUsages:{len(expectedUsage)}")
            self.check_resource_usage(res, expectedUsage)

