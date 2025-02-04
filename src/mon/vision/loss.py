#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""This module implements loss functions for training vision deep learning
models.

This module is built on top of :mod:`mon.nn.loss`.
"""

from __future__ import annotations

__all__ = [
    "ChannelConsistencyLoss", "CharbonnierEdgeLoss", "ColorConstancyLoss",
    "DiceLoss", "EdgeLoss", "ExclusionLoss", "ExposureControlLoss",
    "GradientLoss", "GrayLoss", "GrayscaleLoss", "IlluminationSmoothnessLoss",
    "NonBlurryLoss", "PSNRLoss", "PerceptualL1Loss", "PerceptualLoss",
    "SSIMLoss", "SpatialConsistencyLoss", "StdLoss",
]

import numpy as np
import piqa
import torch

from mon import nn
from mon.globals import LOSSES, Reduction
from mon.nn import functional as F
from mon.nn.loss import *


# region Image Loss

@LOSSES.register(name="charbonnier_edge_loss")
class CharbonnierEdgeLoss(Loss):
    """Implementation of the loss function proposed in the paper "Multi-Stage
    Progressive Image Restoration".
    """
    
    def __init__(
        self,
        reduction: Reduction | str = "mean",
        eps      : float           = 1e-3,
        weight   : list[float]     = [1.0, 0.05],
    ):
        super().__init__(reduction=reduction)
        self.eps = eps
        self.char_loss = CharbonnierLoss(
            eps       = eps,
            weight    = weight[0],
            reduction = reduction,
        )
        self.edge_loss = EdgeLoss(
            eps       = eps,
            weight    = weight[1],
            reduction = reduction
        )
    
    def __str__(self) -> str:
        return f"charbonnier_edge_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        char_loss = self.char_loss(input= input, target=target)
        edge_loss = self.edge_loss(input= input, target=target)
        loss      = char_loss + edge_loss
        return loss


@LOSSES.register(name="channel_consistency_loss")
class ChannelConsistencyLoss(Loss):
    """Channel consistency loss mainly enhances the consistency between the
    original image and the enhanced image in the channel pixel difference
    through KL divergence, and suppresses the generation of noise information
    and invalid features to improve the image enhancement effect.
    
    L_kl = KL[R−B][R′−B′] + KL[R−G][R′−G′] + KL[G−B][G′−B′]
    """
    
    def __init__(
        self,
        reduction : Reduction | str = "mean",
        log_target: bool            = False,
    ):
        super().__init__(reduction=reduction)
        self.log_target = log_target
    
    def __str__(self) -> str:
        return f"channel_consistency_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        assert input.shape == target.shape
        r1 = input[:, 0, :, :]
        g1 = input[:, 1, :, :]
        b1 = input[:, 2, :, :]
        r2 = target[:, 0, :, :]
        g2 = target[:, 1, :, :]
        b2 = target[:, 2, :, :]
        
        d_rb1 = r1 - b1
        d_rb2 = r2 - b2
        d_rg1 = r1 - g1
        d_rg2 = r2 - g2
        d_gb1 = g1 - b1
        d_gb2 = g2 - b2
        
        kl_rb = F.kl_div(d_rb1, d_rb2, reduction="mean", log_target=self.log_target)
        kl_rg = F.kl_div(d_rg1, d_rg2, reduction="mean", log_target=self.log_target)
        kl_gb = F.kl_div(d_gb1, d_gb2, reduction="mean", log_target=self.log_target)
        
        loss = kl_rb + kl_rg + kl_gb
        loss = reduce_loss(loss=loss, reduction=self.reduction)
        return loss


@LOSSES.register(name="color_constancy_loss")
class ColorConstancyLoss(Loss):
    """A color constancy loss to correct the potential color deviations in the
    enhanced image and also build the relations among the three adjusted
    channels.

    References:
        https://github.com/Li-Chongyi/Zero-DCE/blob/master/Zero-DCE_code/Myloss.py
    """
    
    def __init__(self, reduction: Reduction | str = "mean"):
        super().__init__(reduction=reduction)
    
    def __str__(self) -> str:
        return f"color_constancy_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        mean_rgb   = torch.mean(input, [2, 3], keepdim=True)
        mr, mg, mb = torch.split(mean_rgb, 1, dim=1)
        d_rg = torch.pow(mr - mg, 2)
        d_rb = torch.pow(mr - mb, 2)
        d_gb = torch.pow(mb - mg, 2)
        loss = torch.pow(
            torch.pow(d_rg, 2) + torch.pow(d_rb, 2) + torch.pow(d_gb, 2), 0.5
        )
        loss = reduce_loss(loss=loss, reduction=self.reduction)
        return loss


@LOSSES.register(name="dice_loss")
class DiceLoss(Loss):
    
    def __init__(
        self,
        reduction: Reduction | str = "mean",
        smooth   : float           = 1.0,
    ):
        super().__init__(reduction=reduction)
        self.smooth = smooth
    
    def __str__(self) -> str:
        return f"dice_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        assert input.shape == target.shape
        input  = input[ : , 0].contiguous().view(-1)
        target = target[: , 0].contiguous().view(-1)
        intersection = (input * target).sum()
        dice_coeff   = (2.0 * intersection + self.smooth) / (input.sum() + target.sum() + self.smooth)
        loss = 1.0 - dice_coeff
        return loss


@LOSSES.register(name="edge_loss")
class EdgeLoss(Loss):
    
    def __init__(self, reduction: Reduction | str = "mean", eps: float = 1e-3):
        super().__init__(reduction=reduction)
        self.eps = eps
        k = torch.Tensor([[0.05, 0.25, 0.4, 0.25, 0.05]])
        self.kernel = torch.matmul(k.t(), k).unsqueeze(0).repeat(3, 1, 1, 1)
    
    def __str__(self) -> str:
        return f"edge_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        loss = torch.sqrt(
            (self.laplacian_kernel(input) - self.laplacian_kernel(target)) ** 2
            + (self.eps * self.eps)
        )
        loss = reduce_loss(loss=loss, reduction=self.reduction)
        return loss
    
    def conv_gauss(self, image: torch.Tensor) -> torch.Tensor:
        if self.kernel.devices != image.device:
            self.kernel = self.kernel.to(image.device)
        n_channels, _, kw, kh = self.kernel.shape
        image = F.pad(
            image,
            (kw // 2, kh // 2, kw // 2, kh // 2),
            mode="replicate"
        )
        return F.conv2d(image, self.kernel, groups=n_channels)
    
    def laplacian_kernel(self, image: torch.Tensor) -> torch.Tensor:
        filtered   = self.conv_gauss(image)  # filter
        down       = filtered[:, :, ::2, ::2]  # downsample
        new_filter = torch.zeros_like(filtered)
        new_filter[:, :, ::2, ::2] = down * 4  # upsample
        filtered = self.conv_gauss(new_filter)  # filter
        diff     = image - filtered
        return diff


@LOSSES.register(name="exclusion_loss")
class ExclusionLoss(Loss):
    """Loss on the gradient.
    Based on: http://openaccess.thecvf.com/content_cvpr_2018/papers
    /Zhang_Single_Image_Reflection_CVPR_2018_paper.pdf

    References:
        https://github.com/liboyun/ZID/blob/master/net/losses.py
    """
    
    def __init__(self, reduction: Reduction | str = "mean", level: int = 3):
        super().__init__(reduction=reduction)
        self.level    = level
        self.avg_pool = nn.AvgPool2d(kernel_size = 2, stride = 2)
        self.sigmoid  = nn.Sigmoid()
    
    def __str__(self) -> str:
        return f"exclusion_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor | None = None
    ) -> torch.Tensor:
        grad_x_loss, grad_y_loss = self.get_gradients(input, target)
        loss_grad_xy = sum(grad_x_loss) / (self.level * 9) + sum(
            grad_y_loss
        ) / (self.level * 9)
        loss = loss_grad_xy / 2.0
        return loss
    
    def get_gradients(
        self,
        input : torch.Tensor,
        target: torch.Tensor,
    ) -> tuple[list, list]:
        grad_x_loss = []
        grad_y_loss = []
        
        for l in range(self.level):
            grad_x1, grad_y1 = self.compute_gradient(input)
            grad_x2, grad_y2 = self.compute_gradient(target)
            alpha_y      = 1
            alpha_x      = 1
            grad_x1_s    = (self.sigmoid(grad_x1) * 2) - 1
            grad_y1_s    = (self.sigmoid(grad_y1) * 2) - 1
            grad_x2_s    = (self.sigmoid(grad_x2 * alpha_x) * 2) - 1
            grad_y2_s    = (self.sigmoid(grad_y2 * alpha_y) * 2) - 1
            grad_x_loss += self._all_comb(grad_x1_s, grad_x2_s)
            grad_y_loss += self._all_comb(grad_y1_s, grad_y2_s)
            input        = self.avg_pool(input)
            target       = self.avg_pool(target)
        return grad_x_loss, grad_y_loss
    
    def all_comb(self, grad1_s: torch.Tensor, grad2_s: torch.Tensor) -> list:
        v = []
        for i in range(3):
            for j in range(3):
                v.append(
                    torch.mean(
                        ((grad1_s[:, j, :, :] ** 2) * (grad2_s[:, i, :, :] ** 2))
                    ) ** 0.25
                )
        return v
    
    def compute_gradient(
        self,
        input: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        grad_x = input[:, :, 1:, :] - input[:, :, :-1, :]
        grad_y = input[:, :, :, 1:] - input[:, :, :, :-1]
        return grad_x, grad_y


@LOSSES.register(name="exposure_control_loss")
class ExposureControlLoss(Loss):
    """Exposure Control Loss measures the distance between the average intensity
    value of a local region to the well-exposedness level E.

    References:
        https://github.com/Li-Chongyi/Zero-DCE/blob/master/Zero-DCE_code
        /Myloss.py

    Args:
        patch_size: Kernel size for pooling layer.
        mean_val:
        reduction: Reduction value to use.
    """
    
    def __init__(
        self,
        reduction : Reduction | str = "mean",
        patch_size: int | list[int] = 16,
        mean_val  : float           = 0.6,
    ):
        super().__init__(reduction=reduction)
        self.patch_size = patch_size
        self.mean_val   = mean_val
        self.pool       = nn.AvgPool2d(self.patch_size)
    
    def __str__(self) -> str:
        return f"exposure_control_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        x = input
        x = torch.mean(x, 1, keepdim=True)
        mean = self.pool(x)
        loss = torch.pow(
            mean - torch.FloatTensor([self.mean_val]).to(input.device), 2
        )
        loss = reduce_loss(loss=loss, reduction=self.reduction)
        return loss


@LOSSES.register(name="gradient_loss")
class GradientLoss(Loss):
    """L1 loss on the gradient of the image."""
    
    def __init__(self, reduction: Reduction | str = "mean"):
        super().__init__(reduction=reduction)
    
    def __str__(self) -> str:
        return f"gradient_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        gradient_a_x = torch.abs(input[:, :, :, :-1] - input[:, :, :, 1:])
        gradient_a_y = torch.abs(input[:, :, :-1, :] - input[:, :, 1:, :])
        loss = reduce_loss(
            loss=torch.mean(gradient_a_x) + torch.mean(gradient_a_y),
            reduction=self.reduction
        )
        return loss


@LOSSES.register(name="gray_loss")
class GrayLoss(Loss):
    """Gray Loss."""
    
    def __init__(self, reduction: Reduction | str = "mean"):
        super().__init__(reduction=reduction)
        self.mse = MSELoss(reduction=reduction)
    
    def __str__(self) -> str:
        return f"gray_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        loss = 1.0 / self.mse(
            input  = input,
            target = torch.ones_like(input) * 0.5,
        )
        return loss


@LOSSES.register(name="grayscale_loss")
class GrayscaleLoss(Loss):
    """Grayscale Loss."""
    
    def __init__(self, reduction: Reduction | str = "mean"):
        super().__init__(reduction=reduction)
        self.mse = MSELoss(reduction=reduction)
    
    def __str__(self) -> str:
        return f"grayscale_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        input_g  = torch.mean(input, 1, keepdim=True)
        target_g = torch.mean(target, 1, keepdim=True)
        loss     = self.mse(input=input_g, target=target_g)
        return loss


@LOSSES.register(name="illumination_smoothness_loss")
class IlluminationSmoothnessLoss(Loss):
    """Illumination Smoothness Loss preserve the mono-tonicity relations
    between neighboring pixels, we add an illumination smoothness loss to each
    curve parameter map A.
    
    References:
        https://github.com/Li-Chongyi/Zero-DCE/blob/master/Zero-DCE_code
        /Myloss.py
    """
    
    def __init__(
        self,
        reduction     : Reduction | str = "mean",
        tv_loss_weight: int             = 1
    ):
        super().__init__(reduction=reduction)
        self.tv_loss_weight = tv_loss_weight
    
    def __str__(self) -> str:
        return f"illumination_smoothness_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        x       = input
        b       = x.size()[0]
        h_x     = x.size()[2]
        w_x     = x.size()[3]
        count_h = (x.size()[2] - 1) * x.size()[3]
        count_w = x.size()[2] * (x.size()[3] - 1)
        h_tv = torch.pow((x[:, :, 1:, :] - x[:, :, :h_x - 1, :]), 2).sum()
        w_tv = torch.pow((x[:, :, :, 1:] - x[:, :, :, :w_x - 1]), 2).sum()
        loss = self.tv_loss_weight * 2 * (h_tv / count_h + w_tv / count_w) / b
        return loss


@LOSSES.register(name="non_blurry_loss")
class NonBlurryLoss(Loss):
    """MSELoss on the distance to 0.5."""
    
    def __init__(self, reduction: Reduction | str = "mean"):
        super().__init__(reduction=reduction)
        self.mse = MSELoss(reduction=reduction)
    
    def __str__(self) -> str:
        return f"non_blurry_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor = None
    ) -> torch.Tensor:
        loss = 1.0 - self.mse(
            input  = input,
            target = torch.ones_like(input) * 0.5,
        )
        return loss


@LOSSES.register(name="perceptual_l1_loss")
class PerceptualL1Loss(Loss):
    """Loss = weights[0] * Perceptual Loss + weights[1] * L1 Loss."""
    
    def __init__(self, vgg: nn.Module, reduction: Reduction | str = "mean"):
        super().__init__(reduction=reduction)
        self.per_loss = PerceptualLoss(
            vgg       = vgg,
            reduction = reduction,
        )
        self.l1_loss = L1Loss(
            reduction=reduction,
        )
        self.layer_name_mapping = {
            "3" : "relu1_2",
            "8" : "relu2_2",
            "15": "relu3_3"
        }
    
    def __str__(self) -> str:
        return f"perceptual_l1_Loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor
    ) -> torch.Tensor:
        per_loss = self.per_loss(input=input, target=target)
        l1_loss  = self.l1_loss(input=input, target=target)
        loss     = per_loss + l1_loss
        return loss


@LOSSES.register(name="perceptual_loss")
class PerceptualLoss(Loss):
    """Perceptual Loss."""
    
    def __init__(self, vgg: nn.Module, reduction: Reduction | str = "mean"):
        super().__init__(reduction=reduction)
        self.mse = MSELoss(reduction=reduction)
        self.vgg = vgg
        self.vgg.freeze()
    
    def __str__(self) -> str:
        return f"perceptual_Loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor
    ) -> torch.Tensor:
        if self.vgg.device != input[0].devices:
            self.vgg = self.vgg.to(input[0].devices)
        input_feats  = self.vgg(input)
        target_feats = self.vgg(target)
        loss = self.mse(input=input_feats, target=target_feats)
        return loss


@LOSSES.register(name="psnr_loss")
class PSNRLoss(Loss):
    """PSNR loss. Modified from BasicSR: https://github.com/xinntao/BasicSR"""
    
    def __init__(
        self,
        reduction: Reduction | str = "mean",
        max_val  : float           = 1.0
    ):
        super().__init__(reduction=reduction)
        self.mse     = MSELoss(reduction=reduction)
        self.max_val = max_val
    
    def __str__(self) -> str:
        return f"psnr_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor
    ) -> torch.Tensor:
        psnr = 10.0 * torch.log10(self.max_val ** 2 / self.mse(input, target))
        loss = -1.0 * psnr
        loss = reduce_loss(loss=loss, reduction=self.reduction)
        return loss


@LOSSES.register(name="spatial_consistency_loss")
class SpatialConsistencyLoss(Loss):
    """Spatial Consistency Loss (SPA) Loss."""
    
    def __init__(self, reduction: Reduction | str = "mean"):
        super().__init__(reduction=reduction)
        kernel_left  = torch.FloatTensor([[0, 0, 0], [-1, 1, 0], [0, 0, 0]]).unsqueeze(0).unsqueeze(0)
        kernel_right = torch.FloatTensor([[0, 0, 0], [0, 1, -1], [0, 0, 0]]).unsqueeze(0).unsqueeze(0)
        kernel_up    = torch.FloatTensor([[0, -1, 0], [0, 1, 0], [0, 0, 0]]).unsqueeze(0).unsqueeze(0)
        kernel_down  = torch.FloatTensor([[0, 0, 0], [0, 1, 0], [0, -1, 0]]).unsqueeze(0).unsqueeze(0)
        self.weight_left  = nn.Parameter(data=kernel_left, requires_grad=False)
        self.weight_right = nn.Parameter(data=kernel_right, requires_grad=False)
        self.weight_up    = nn.Parameter(data=kernel_up, requires_grad=False)
        self.weight_down  = nn.Parameter(data=kernel_down, requires_grad=False)
        self.pool         = nn.AvgPool2d(4)
    
    def __str__(self) -> str:
        return f"spatial_consistency_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor
    ) -> torch.Tensor:
        if self.weight_left.device != input.device:
            self.weight_left = self.weight_left.to(input.device)
        if self.weight_right.device != input.device:
            self.weight_right = self.weight_right.to(input.device)
        if self.weight_up.device != input.device:
            self.weight_up = self.weight_up.to(input.device)
        if self.weight_down.device != input.device:
            self.weight_down = self.weight_down.to(input.device)
        
        org_mean     = torch.mean(input, 1, keepdim=True)
        enhance_mean = torch.mean(target, 1, keepdim=True)
        
        org_pool     = self.pool(org_mean)
        enhance_pool = self.pool(enhance_mean)
        
        d_org_left  = F.conv2d(org_pool, self.weight_left, padding=1)
        d_org_right = F.conv2d(org_pool, self.weight_right, padding=1)
        d_org_up    = F.conv2d(org_pool, self.weight_up, padding=1)
        d_org_down  = F.conv2d(org_pool, self.weight_down, padding=1)
        
        d_enhance_left  = F.conv2d(enhance_pool, self.weight_left,  padding=1)
        d_enhance_right = F.conv2d(enhance_pool, self.weight_right, padding=1)
        d_enhance_up    = F.conv2d(enhance_pool, self.weight_up,    padding=1)
        d_enhance_down  = F.conv2d(enhance_pool, self.weight_down,  padding=1)
        
        d_left  = torch.pow(d_org_left  - d_enhance_left,  2)
        d_right = torch.pow(d_org_right - d_enhance_right, 2)
        d_up    = torch.pow(d_org_up    - d_enhance_up,    2)
        d_down  = torch.pow(d_org_down  - d_enhance_down,  2)
        loss    = d_left + d_right + d_up + d_down
        loss    = reduce_loss(loss=loss, reduction=self.reduction)
        return loss


@LOSSES.register(name="ssim_loss")
class SSIMLoss(Loss):
    """SSIM Loss. Modified from BasicSR: https://github.com/xinntao/BasicSR"""
    
    def __init__(
        self,
        reduction  : Reduction | str = "mean",
        window_size: int             = 11,
        sigma      : float           = 1.5,
        n_channels : int             = 3,
        value_range: float           = 1.0,
    ):
        super().__init__(reduction=reduction)
        self.ssim = piqa.SSIM(
            window_size = window_size,
            sigma       = sigma,
            n_channels  = n_channels,
            value_range = value_range,
            reduction   = self.reduction,
        )
    
    def __str__(self) -> str:
        return f"ssim_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor
    ) -> torch.Tensor:
        # Compute the ssim map
        ssim_map = self.ssim(input=input, target=target)
        # Compute and reduce the loss
        loss = torch.clamp((1.0 - ssim_map) / 2, min=0, max=1)
        loss = reduce_loss(loss=loss, reduction=self.reduction)
        return loss


@LOSSES.register(name="std_loss")
class StdLoss(Loss):
    """Loss on the variance of the image. Works in the grayscale. If the image
    is smooth, gets zero.
    """
    
    def __init__(self, reduction: Reduction | str = "mean"):
        super().__init__(reduction=reduction)
        blur        = (1 / 25) * np.ones((5, 5))
        blur        = blur.reshape(1, 1, blur.shape[0], blur.shape[1])
        blur        = nn.Parameter(data=torch.FloatTensor(blur), requires_grad=False)
        self.blur   = blur
        image       = np.zeros((5, 5))
        image[2, 2] = 1
        image       = image.reshape(1, 1, image.shape[0], image.shape[1])
        image       = nn.Parameter(data=torch.FloatTensor(image), requires_grad=False)
        self.image  = image
        self.mse    = MSELoss(reduction=reduction)
    
    def __str__(self) -> str:
        return f"std_loss"
    
    def forward(
        self,
        input : torch.Tensor,
        target: torch.Tensor
    ) -> torch.Tensor:
        if self.blur.device != input[0].devices:
            self.blur = self.blur.to(input[0].devices)
        if self.image.device != input[0].devices:
            self.image = self.image.to(input[0].devices)
        
        input_mean = torch.mean(input, 1, keepdim=True)
        loss = self.mse(
            input  = F.conv2d(input_mean, self.image),
            target = F.conv2d(input_mean, self.blur)
        )
        return loss

# endregion
